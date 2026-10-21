# 业务层轮询编排：采集、差分、落库、推送与清理。
# 本文件不直接读配置也不建连接，依赖由入口层注入。
import asyncio
import sqlite3
from typing import TYPE_CHECKING

from ..data.db import utc_now
from ..data.history_store import purge_expired, record_change, record_push
from ..data.subscription_store import list_subscriptions
from ..entity.constants import NOTIFY_CHANGES, NOTIFY_SUMMARY
from ..entity.models import MonitorConfig, Notification, Snapshot
from .collector import CollectorError, fetch_summary
from .detector import changes_key, detect_event_changes
from .parser_api import parse_snapshot
from .text import render_changes, render_summary, resolve_timezone

if TYPE_CHECKING:
    # 只在类型检查时导入 AstrBot，运行与测试环境不需要它
    from astrbot.core.star.context import Context

try:
    # 运行时用 AstrBot 的日志；测试环境没有它，单轮异常只吞掉不中断循环
    from astrbot.api import logger
except ImportError:
    logger = None

try:
    # 主动推送需要消息链；测试环境没有 AstrBot，可用 patch 替换
    from astrbot.api.event import MessageChain
except ImportError:
    MessageChain = None


class Monitor:
    """持有轮询任务与最近一次成功快照。"""

    def __init__(
        self, conn: sqlite3.Connection, config: MonitorConfig, context: "Context"
    ) -> None:
        """只保存依赖；采集与任务启动由 start() / _tick() 负责。"""
        # 数据库连接由入口层打开，业务层不自己建库
        self.conn = conn
        # 配置已由入口层转成 dataclass，这里不再读原始 dict
        self.config = config
        # 推送要用 AstrBot 的 Context，业务层不关心插件实例
        self.context = context
        # 最近一次成功采集的快照；首次成功前为空
        self._snapshot: Snapshot | None = None
        # 后台轮询任务；start() 创建，stop() 取消
        self._task: asyncio.Task[None] | None = None
        # 时区只解析一次，后续渲染复用
        self._tz = resolve_timezone(config.display_timezone)

    async def start(self) -> None:
        """启动后台轮询；关闭时停掉旧任务，重启时先停再建。"""
        # 总开关关闭时保留旧任务没有意义，一并停掉
        if not self.config.enabled:
            await self.stop()
            return
        # 已存在任务（运行中或已结束）先停掉，保证同一时刻只有一个循环
        if self._task is not None:
            await self.stop()
        self._task = asyncio.create_task(self.run())

    async def stop(self) -> None:
        """取消后台轮询并等待退出；没有任务时直接返回。"""
        # 没启动过就不需要取消
        if self._task is None:
            return
        self._task.cancel()
        try:
            # 等任务真正退出，避免 stop 返回后旧循环还在写库
            await self._task
        except asyncio.CancelledError:
            # 取消是预期路径，不当异常往外抛
            pass
        # 清空引用，下一次 start 才能重新创建
        self._task = None

    async def run(self) -> None:
        """轮询循环：按开始时间对齐节拍，配置每轮重读，支持热更新。"""
        while True:
            # 页面把总开关关掉后，下一轮直接退出，任务自然结束
            if not self.config.enabled:
                return
            started = asyncio.get_running_loop().time()
            try:
                await self._tick()
            except Exception:
                # 单轮失败不结束循环；记录堆栈，下一轮继续
                if logger is not None:
                    logger.exception("OpenAI 状态轮询单轮失败")
            # 下一轮按“本轮开始时间 + 间隔”算；本轮超时就不再等待
            interval = self.config.poll_interval_seconds
            elapsed = asyncio.get_running_loop().time() - started
            delay = interval - elapsed
            # 提前跑完才补足剩余间隔；已经超时则立刻开始下一轮
            if delay > 0:
                await asyncio.sleep(delay)

    async def _tick(self) -> None:
        """跑一轮：采集、差分、写记录、推送、换快照、清理。"""
        snapshot = await self._collect()
        # 采集失败保留上一轮快照，也不做清理
        if snapshot is None:
            return
        previous = self._snapshot
        changes = detect_event_changes(previous, snapshot)
        # 首次成功只建基线，不写记录也不推送
        if previous is not None and changes:
            try:
                for event in changes:
                    record_change(self.conn, event, snapshot.fetched_at)
            except Exception:
                # 记录写失败就停止本轮；已写入的行保留，快照与推送都不动
                if logger is not None:
                    logger.exception("变更记录写入失败，本轮不推送")
                return
            # 通知开关关闭时只落库，不推送
            if self.config.notify_enabled:
                message = render_changes(changes, snapshot.fetched_at, self._tz)
                notification = Notification(
                    notify_type=NOTIFY_CHANGES,
                    dedup_key=changes_key(snapshot),
                    message=message,
                )
                await self._dispatch(notification)
        self._snapshot = snapshot
        purge_expired(self.conn, self.config.history_retention_days)

    async def _collect(self) -> Snapshot | None:
        """拉取并解析一轮快照；请求失败或结构异常返回 None。"""
        try:
            summary = await fetch_summary()
        except CollectorError:
            # 超时、非 200、非法 JSON 都归为请求失败；保留上一轮快照
            if logger is not None:
                logger.exception("OpenAI 状态页请求失败")
            return None
        # 采集时间取请求成功后、解析前，代表这一轮拿到数据的时刻
        fetched_at = utc_now()
        try:
            return parse_snapshot(summary, fetched_at)
        except ValueError:
            # 200 但字段形状不符；不猜字段，保留上一轮快照并记结构异常
            if logger is not None:
                logger.exception("OpenAI 状态页接口结构异常")
            return None

    async def _dispatch(self, notification: Notification) -> None:
        """给每个启用订阅推送这一条通知；相邻两条间隔 1 秒，单条失败继续。"""
        subscriptions = list_subscriptions(self.conn, only_enabled=True)
        # 没有启用订阅时不发消息，也不写推送记录
        if not subscriptions:
            return
        total = len(subscriptions)
        sent = 0
        for subscription in subscriptions:
            sent += 1
            chain = MessageChain().message(notification.message)
            try:
                ok = await self.context.send_message(subscription.session, chain)
                # 返回 False 表示没有找到匹配的平台，也算失败
                error = "" if ok else "未找到匹配的平台"
            except Exception as exc:
                # 单个会话失败不中断其余会话，异常原文写进推送记录
                ok = False
                error = f"{type(exc).__name__}: {exc}"
            try:
                record_push(
                    self.conn,
                    subscription.session,
                    notification.dedup_key,
                    notification.notify_type,
                    notification.message,
                    ok,
                    error,
                )
            except Exception:
                # 记录写失败只影响排查，不拦后续会话的推送
                if logger is not None:
                    logger.exception("推送记录写入失败")
            if not ok and logger is not None:
                logger.warning(f"推送到 {subscription.session} 失败：{error}")
            # 相邻两条之间等 1 秒，最后一条不等
            if sent < total:
                await asyncio.sleep(1)

    async def push_summary(self, session: str) -> bool:
        """开启订阅时主动查一次并推当前状态；返回摘要是否成功送达。"""
        # 全局通知关闭时只开订阅，不查也不推；开启本身没出错
        if not self.config.notify_enabled:
            return True
        snapshot = await self._collect()
        # 主动查询失败：订阅仍开启，但这次摘要取不到
        if snapshot is None:
            return False
        message = render_summary(snapshot, self._tz)
        # 产品只支持群聊，确认消息固定说“本群”
        prefix = "OpenAI 状态监控已开启，若 OpenAI 官方状态变更，会推送到本群"
        message = f"{prefix}\n{message}"
        dedup_key = f"summary:{snapshot.fetched_at}"
        try:
            chain = MessageChain().message(message)
            ok = await self.context.send_message(session, chain)
            error = "" if ok else "未找到匹配的平台"
        except Exception as exc:
            # 会话非法或平台发送失败都算这一条失败，原文留给推送记录
            ok = False
            error = f"{type(exc).__name__}: {exc}"
        try:
            record_push(self.conn, session, dedup_key, NOTIFY_SUMMARY, message, ok, error)
        except Exception:
            if logger is not None:
                logger.exception("摘要推送记录写入失败")
        if not ok and logger is not None:
            logger.warning(f"摘要推送到 {session} 失败：{error}")
        return ok

    def snapshot(self) -> Snapshot | None:
        """返回最近一次成功采集的快照；还没有就返回 None。"""
        return self._snapshot
