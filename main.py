# 入口层：AstrBot 插件类、Web API 注册与 oaistatus 命令。
# 只做参数校验与转发，采集、落库、推送都在 business/ 与 data/。
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.star import Context, Star
from astrbot.api.web import error_response, json_response, request

from .business.monitor import Monitor
from .business.text import render_help, render_status_reply, resolve_timezone
from .data.db import connect, get_db_path, init_db
from .data.history_store import list_changes
from .data.subscription_store import (
    create,
    delete,
    disable_session,
    enable_session,
    get_by_id,
    list_subscriptions,
    update,
)
from .entity.constants import (
    COMMAND_NAME,
    PLUGIN_NAME,
    SUBCOMMAND_HELP,
    SUBCOMMAND_OFF,
    SUBCOMMAND_ON,
)
from .entity.models import MonitorConfig


class Plugin(Star):
    """OpenAI 状态页监控插件。"""

    def __init__(self, context: Context, config: dict | None = None) -> None:
        """建库、转换配置、创建监控并注册路由。"""
        super().__init__(context)
        # 配置由 AstrBot 按 _conf_schema.json 读出；缺省时用空 dict
        self.config = config or {}
        # 数据库文件在插件数据目录；连接只在这里开一次
        self.conn = connect(get_db_path())
        init_db(self.conn)
        # 旧库里的会话前缀可能是适配器名；按当前平台 id 迁移
        self._migrate_sessions()
        # 原始 dict 只在这里转成 dataclass，业务层不碰配置键名
        self.monitor = Monitor(
            self.conn,
            MonitorConfig(
                enabled=bool(self.config.get("enabled", False)),
                poll_interval_seconds=int(self.config.get("poll_interval_seconds", 60)),
                notify_enabled=bool(self.config.get("notify_enabled", True)),
                history_retention_days=int(self.config.get("history_retention_days", 30)),
                display_timezone=str(self.config.get("display_timezone", "Asia/Shanghai")),
            ),
            context,
        )
        self._register_routes()

    def _onebot_platform(self):
        """找当前 OneBot 平台实例；平台 id 可自定义（如 napcat），不能按名字写死。"""
        platform = self.context.get_platform("aiocqhttp")
        if platform is not None:
            return platform
        manager = getattr(self.context, "platform_manager", None)
        for item in getattr(manager, "platform_insts", []):
            bot = getattr(item, "bot", None)
            # OneBot 适配器的 bot 都有 call_action；用它识别，不依赖平台名
            if bot is not None and hasattr(bot, "call_action"):
                return item
        return None

    def _normalize_session(self, session: str) -> str:
        """把 UMO 前缀改成平台实例 id；兼容历史 aiocqhttp 前缀。"""
        platform = self._onebot_platform()
        if platform is None:
            return session
        parts = session.split(":", 2)
        if len(parts) != 3:
            return session
        return f"{platform.meta().id}:{parts[1]}:{parts[2]}"

    def _migrate_sessions(self) -> None:
        """启动时把已有订阅的会话前缀迁移到当前平台 id。"""
        platform = self._onebot_platform()
        if platform is None:
            return
        platform_id = platform.meta().id
        for subscription in list_subscriptions(self.conn):
            parts = subscription.session.split(":", 2)
            if len(parts) != 3:
                continue
            session = f"{platform_id}:{parts[1]}:{parts[2]}"
            if session != subscription.session:
                update(
                    self.conn,
                    subscription.id,
                    session,
                    subscription.note,
                    subscription.enabled,
                )

    async def _fetch_group_name(self, group_id: str) -> str | None:
        """按群号取群名；平台缺失或接口失败返回 None。"""
        platform = self._onebot_platform()
        if platform is None:
            return None
        try:
            info = await platform.bot.call_action("get_group_info", group_id=int(group_id))
        except Exception:
            return None
        if isinstance(info, dict):
            name = info.get("group_name")
            if name:
                return str(name)
        return None

    async def initialize(self) -> None:
        """插件加载后启动轮询；总开关关闭时 start 不建任务。"""
        await self.monitor.start()
        # 启动结果写一行日志，便于在 AstrBot 日志里确认配置是否生效
        self.logger.info("OpenAI 状态监控初始化完成，enabled=%s", self.monitor.config.enabled)

    async def terminate(self) -> None:
        """插件卸载时先停轮询，再关数据库连接。"""
        # 先停任务：旧循环可能正在写库，关连接后再停会报错
        await self.monitor.stop()
        self.conn.close()
        self.logger.info("OpenAI 状态监控已停止")

    @filter.command(COMMAND_NAME)
    async def oaistatus(self, event: AstrMessageEvent, sub: str = ""):
        """查状态、开/关本群通知、显示帮助。"""
        # 指令名可能被 AstrBot 指令管理改过，帮助用实际触发的首个 token
        command_name = event.message_str.strip().split(maxsplit=1)[0] or COMMAND_NAME
        raw_session = event.unified_msg_origin
        # 产品只支持群聊；私聊直接忽略，也不让消息继续进 LLM
        if ":GroupMessage:" not in raw_session:
            event.stop_event()
            return
        # 平台 id 可能不是 aiocqhttp（如 napcat），统一改写成实例 id
        session = self._normalize_session(raw_session)
        if sub == SUBCOMMAND_HELP:
            yield event.plain_result(render_help(command_name))
            event.stop_event()
            return
        if sub == SUBCOMMAND_ON:
            subscription, _ = enable_session(self.conn, session, "")
            # 命令开启也补群名：备注为空时拉一次，写进订阅表
            if not subscription.note:
                group_id = session.split(":", 2)[2]
                name = await self._fetch_group_name(group_id)
                if name:
                    update(
                        self.conn,
                        subscription.id,
                        session,
                        name,
                        subscription.enabled,
                    )
            # 全局监控或全局通知关闭时只写订阅，不查也不推
            if not self.monitor.config.enabled or not self.monitor.config.notify_enabled:
                yield event.plain_result("已开启，全局通知关闭，暂不推送。")
                event.stop_event()
                return
            # 全局都开着才主动查一次并推当前状态
            if await self.monitor.push_summary(session):
                # 确认消息本身已包含状态，不再额外回一条
                event.stop_event()
                return
            yield event.plain_result("已开启，但暂时取不到状态。")
            event.stop_event()
            return
        if sub == SUBCOMMAND_OFF:
            # 关成功与从没订阅过给不同提示，避免用户以为操作生效
            if disable_session(self.conn, session):
                yield event.plain_result("已关闭本群通知。")
            else:
                yield event.plain_result("本群还没有订阅。")
            event.stop_event()
            return
        # 不带子命令就是查状态；监控总开关关掉时明确提示
        if not sub:
            if not self.monitor.config.enabled:
                yield event.plain_result("监控已关闭。")
                event.stop_event()
                return
            timezone = resolve_timezone(self.monitor.config.display_timezone)
            yield event.plain_result(render_status_reply(self.monitor.snapshot(), timezone))
            event.stop_event()
            return
        # 认不出的子命令按帮助处理，不静默失败
        yield event.plain_result(render_help(command_name))
        event.stop_event()

    async def page_get_settings(self):
        """返回概览页要显示的五个非密钥配置。"""
        config = self.monitor.config
        return json_response(
            {
                "settings": {
                    "enabled": config.enabled,
                    "poll_interval_seconds": config.poll_interval_seconds,
                    "notify_enabled": config.notify_enabled,
                    "history_retention_days": config.history_retention_days,
                    "display_timezone": config.display_timezone,
                }
            }
        )

    async def page_save_settings(self):
        """保存五个配置并热更新监控；非法值整单 400，不落库。"""
        payload = await request.json(default={})
        # 请求体必须是对象，数组或字符串没法按字段校验
        if not isinstance(payload, dict):
            return error_response("请求体必须是 JSON 对象")
        current = self.monitor.config
        enabled = payload.get("enabled", current.enabled)
        notify_enabled = payload.get("notify_enabled", current.notify_enabled)
        interval = payload.get("poll_interval_seconds", current.poll_interval_seconds)
        retention = payload.get("history_retention_days", current.history_retention_days)
        timezone_name = payload.get("display_timezone", current.display_timezone)
        # bool 是 int 的子类，先单独拦掉，避免 True 被当成 1
        if not isinstance(enabled, bool) or not isinstance(notify_enabled, bool):
            return error_response("enabled 与 notify_enabled 必须是布尔值")
        if isinstance(interval, bool) or not isinstance(interval, int) or not 30 <= interval <= 3600:
            return error_response("poll_interval_seconds 必须是 30–3600 的整数")
        if (
            isinstance(retention, bool)
            or not isinstance(retention, int)
            or not 1 <= retention <= 365
        ):
            return error_response("history_retention_days 必须是 1–365 的整数")
        if not isinstance(timezone_name, str) or not timezone_name:
            return error_response("display_timezone 必须是非空的 IANA 时区名")
        try:
            ZoneInfo(timezone_name)
        except (ZoneInfoNotFoundError, ValueError):
            return error_response("display_timezone 必须是合法的 IANA 时区名")
        settings = {
            "enabled": enabled,
            "poll_interval_seconds": interval,
            "notify_enabled": notify_enabled,
            "history_retention_days": retention,
            "display_timezone": timezone_name,
        }
        # 先落配置文件，再替换内存配置并重启任务，让新间隔与开关立即生效
        self.config.save_config(settings)  # type: ignore[attr-defined]
        self.monitor.config = MonitorConfig(**settings)
        await self.monitor.start()
        return json_response({"saved": True, "settings": settings})

    async def page_get_status(self):
        """返回监控开关与当前快照；监控关闭时不返回旧快照。"""
        config = self.monitor.config
        # 总开关关闭时页面只显示“监控已关闭”，旧数据不展示
        if not config.enabled:
            return json_response({"enabled": False, "snapshot": None})
        snapshot = self.monitor.snapshot()
        # 首次采集还没成功时没有可展示的快照
        if snapshot is None:
            return json_response({"enabled": True, "snapshot": None})
        events = []
        for event in snapshot.events:
            events.append(
                {
                    "change_id": event.change_id,
                    "change_type": event.change_type,
                    "title": event.title,
                    "status": event.status,
                    "link": event.link,
                    "components": event.components,
                    "message": event.message,
                }
            )
        return json_response(
            {
                "enabled": True,
                "snapshot": {
                    "status": snapshot.status,
                    "fetched_at": snapshot.fetched_at,
                    "events": events,
                },
            }
        )

    async def page_list_subscriptions(self):
        """返回全部群订阅（含停用），按创建顺序给页面改开关。"""
        subscriptions = list_subscriptions(self.conn)
        items = []
        for subscription in subscriptions:
            parts = subscription.session.split(":", 2)
            # 产品只支持群聊；历史私聊记录不展示
            if len(parts) != 3 or parts[1] != "GroupMessage":
                continue
            items.append(
                {
                    "id": subscription.id,
                    "group_id": parts[2],
                    "note": subscription.note,
                    "enabled": subscription.enabled,
                    "created_at": subscription.created_at,
                    "updated_at": subscription.updated_at,
                }
            )
        return json_response({"subscriptions": items})

    async def page_create_subscription(self):
        """页面新增群订阅；群号重复时返回 400。"""
        payload = await request.json(default={})
        # 请求体必须是对象，数组或字符串没法按字段校验
        if not isinstance(payload, dict):
            return error_response("请求体必须是 JSON 对象")
        group_id = payload.get("group_id", "")
        note = payload.get("note", "")
        enabled = payload.get("enabled", True)
        # 产品只支持群聊，页面只填群号；完整 UMO 由后端拼
        if not isinstance(group_id, str) or not group_id.strip().isdigit():
            return error_response("group_id 必须是纯数字群号")
        if not isinstance(note, str):
            return error_response("note 必须是字符串")
        if not isinstance(enabled, bool):
            return error_response("enabled 必须是布尔值")
        platform = self._onebot_platform()
        if platform is None:
            return error_response("未找到 OneBot 平台")
        session = f"{platform.meta().id}:GroupMessage:{group_id.strip()}"
        ok, reason = create(self.conn, session, note, enabled)
        if not ok:
            return error_response(reason or "新增订阅失败")
        pushed = False
        # 新增的是启用订阅且全局两个开关都开时，主动推一次当前状态
        if enabled and self.monitor.config.enabled and self.monitor.config.notify_enabled:
            pushed = await self.monitor.push_summary(session)
        return json_response({"created": True, "summary_pushed": pushed})

    async def page_update_subscription(self, sub_id: str):
        """页面编辑群号、备注与开关；群号变化或停用改启用时补推摘要。"""
        try:
            target_id = int(sub_id)
        except ValueError:
            return error_response("sub_id 必须是整数")
        if target_id < 1:
            return error_response("sub_id 必须是正整数")
        payload = await request.json(default={})
        if not isinstance(payload, dict):
            return error_response("请求体必须是 JSON 对象")
        current = get_by_id(self.conn, target_id)
        # 记录被别处删掉时明确 404，页面应刷新列表
        if current is None:
            return error_response("订阅不存在", status_code=404)
        current_parts = current.session.split(":", 2)
        default_group = current_parts[2] if len(current_parts) == 3 else ""
        group_id = payload.get("group_id", default_group)
        note = payload.get("note", current.note)
        enabled = payload.get("enabled", current.enabled)
        if not isinstance(group_id, str) or not group_id.strip().isdigit():
            return error_response("group_id 必须是纯数字群号")
        if not isinstance(note, str):
            return error_response("note 必须是字符串")
        if not isinstance(enabled, bool):
            return error_response("enabled 必须是布尔值")
        platform = self._onebot_platform()
        if platform is None:
            return error_response("未找到 OneBot 平台")
        session = f"{platform.meta().id}:GroupMessage:{group_id.strip()}"
        if not update(self.conn, target_id, session, note, enabled):
            return error_response("订阅不存在", status_code=404)
        pushed = False
        # 群号变化或“停用 → 启用”时，给新目标补推一次确认摘要
        if (
            enabled
            and (not current.enabled or current.session != session)
            and self.monitor.config.enabled
            and self.monitor.config.notify_enabled
        ):
            pushed = await self.monitor.push_summary(session)
        return json_response({"updated": True, "summary_pushed": pushed})

    async def page_delete_subscription(self, sub_id: str):
        """删除订阅；主键不存在或已删除返回 404。"""
        try:
            target_id = int(sub_id)
        except ValueError:
            return error_response("sub_id 必须是整数")
        if target_id < 1:
            return error_response("sub_id 必须是正整数")
        # 没删到行说明记录已不存在，页面应刷新列表
        if not delete(self.conn, target_id):
            return error_response("订阅不存在", status_code=404)
        return json_response({"deleted": True})

    async def page_list_changes(self):
        """变更记录分页；默认每页 20 条，最多 100 条。"""
        page = request.query.get("page", 1, type=int)
        size = request.query.get("size", 20, type=int)
        # 参数越界或不是整数时回到默认值，页面总能拿到一页数据
        if page is None or page < 1:
            page = 1
        if size is None or size < 1:
            size = 20
        if size > 100:
            size = 100
        rows, total = list_changes(self.conn, page, size)
        return json_response({"changes": rows, "total": total, "page": page, "size": size})

    async def page_get_group_name(self):
        """按群号取群名，供页面填入备注。"""
        group_id = request.query.get("group_id", "")
        if not isinstance(group_id, str) or not group_id.strip().isdigit():
            return error_response("group_id 必须是纯数字群号")
        name = await self._fetch_group_name(group_id.strip())
        if name is None:
            return error_response("拉取群名失败或没有取到群名")
        return json_response({"group_name": name})

    def _register_routes(self) -> None:
        """注册三个 Tab 用到的全部 Web API；路径参数用 <sub_id>。"""
        routes = [
            ("settings", self.page_get_settings, ["GET"], "读取插件配置"),
            ("settings/save", self.page_save_settings, ["POST"], "保存插件配置"),
            ("status", self.page_get_status, ["GET"], "读取当前快照"),
            ("subscriptions", self.page_list_subscriptions, ["GET"], "列出订阅"),
            ("subscriptions", self.page_create_subscription, ["POST"], "新增订阅"),
            (
                "subscriptions/<sub_id>/update",
                self.page_update_subscription,
                ["POST"],
                "编辑订阅",
            ),
            (
                "subscriptions/<sub_id>/delete",
                self.page_delete_subscription,
                ["POST"],
                "删除订阅",
            ),
            ("history", self.page_list_changes, ["GET"], "列出变更记录"),
            ("group-name", self.page_get_group_name, ["GET"], "按群号取群名"),
        ]
        for suffix, handler, methods, desc in routes:
            self.context.register_web_api(f"/{PLUGIN_NAME}/{suffix}", handler, methods, desc)
