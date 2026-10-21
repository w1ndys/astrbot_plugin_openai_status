# 业务层文案：时区解析与后续的通知/命令文本渲染。
# 本文件不访问数据库；AstrBot 的 logger 只在运行时存在，测试环境可缺席。
from datetime import datetime, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from ..entity.constants import (
    CLOSED_EVENT_STATUSES,
    DEFAULT_TIMEZONE,
    EVENT_TYPE_LABELS,
    STATUS_ABNORMAL,
    STATUS_LABELS,
    SUBCOMMAND_HELP,
    SUBCOMMAND_OFF,
    SUBCOMMAND_ON,
    UPCOMING_EVENT_STATUSES,
)
from ..entity.models import Snapshot, StatusEvent

# 通知里正文最多保留这么多字符；接口的 message_string 可能很长
_MESSAGE_LIMIT = 200

try:
    from astrbot.api import logger
except ImportError:
    # 测试环境不装 AstrBot；运行时一定有，缺了只影响非法时区的 warning
    logger = None


def resolve_timezone(raw: str) -> ZoneInfo:
    """把配置里的 IANA 名称解析成时区；空或非法时回退默认并记 warning。"""
    # 空配置直接回退，不必尝试解析
    if not raw:
        return DEFAULT_TIMEZONE
    try:
        return ZoneInfo(raw)
    except (ZoneInfoNotFoundError, ValueError):
        # 运行时非法值回退；页面保存会在入口层直接拒绝，不走到这里
        if logger is not None:
            logger.warning(f"display_timezone 不是合法 IANA 名称：{raw!r}，回退到 Asia/Shanghai")
        return DEFAULT_TIMEZONE


def to_local(fetched_at: str, tz: ZoneInfo) -> str:
    """把 UTC ISO 采集时间按传入时区渲染成 YYYY-MM-DD HH:MM:SS。"""
    # 库里的时间固定是 UTC 带 Z，先按同一格式解析，再换到展示时区
    moment = datetime.strptime(fetched_at, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    return moment.astimezone(tz).strftime("%Y-%m-%d %H:%M:%S")


def _short_message(message: str) -> str:
    """把更新正文压成一行并截断，避免一条通知被长文本撑满。"""
    # 正文里的换行在群消息里会拆成多段；统一换成空格，版面更稳
    one_line = " ".join(message.split())
    # 超长时截断并加省略号，提示还有后续内容
    if len(one_line) > _MESSAGE_LIMIT:
        return one_line[:_MESSAGE_LIMIT] + "…"
    return one_line


def _event_head(index: int, event: StatusEvent) -> str:
    """事件标题行：编号、标题、类型与状态。"""
    # 标题正常不会为空；真为空时给个占位，不让消息出现空条目
    title = event.title or "未命名事件"
    change_type = EVENT_TYPE_LABELS.get(event.change_type, event.change_type)
    status = STATUS_LABELS.get(event.status, event.status)
    return f"{index}. {title}（{change_type} / {status}）"


def _event_details(event: StatusEvent) -> list[str]:
    """事件详情行：受影响组件、最新进展与链接；没有的项直接省略。"""
    lines: list[str] = []
    # 接口只给组件 ID，解析层已换成名称；有名称才展示
    if event.components:
        lines.append(f"   影响组件：{'、'.join(event.components)}")
    # 最新一条更新正文对订阅者最有用；空正文不占行
    if event.message:
        lines.append(f"   最新进展：{_short_message(event.message)}")
    lines.append(f"   {event.link}")
    return lines


def render_changes(changes: list[StatusEvent], fetched_at: str, tz: ZoneInfo) -> str:
    """把一轮变化汇总成一条消息：每条列出标题、类型、状态、组件、进展与链接。"""
    lines = [f"检测到 {len(changes)} 条变化（{to_local(fetched_at, tz)}）"]
    for index, event in enumerate(changes, start=1):
        lines.append(_event_head(index, event))
        lines.extend(_event_details(event))
    return "\n".join(lines)


def render_summary(snapshot: Snapshot, tz: ZoneInfo) -> str:
    """订阅开启时的当前状态摘要；只列进行中事件，计划维护单独提示。"""
    moment = to_local(snapshot.fetched_at, tz)
    active = [
        event
        for event in snapshot.events
        if event.status not in CLOSED_EVENT_STATUSES
        and event.status not in UPCOMING_EVENT_STATUSES
    ]
    upcoming = [event for event in snapshot.events if event.status in UPCOMING_EVENT_STATUSES]
    # 有组件异常但没有任何事件时，状态仍是异常，给一句不带事件的说明
    if snapshot.status == STATUS_ABNORMAL and not active:
        lines = [f"当前状态：有组件状态异常（{moment}）"]
    # 没有进行中事件就是页面上的“一切运行正常”，只回一句状态
    elif not active:
        lines = [f"当前状态：一切运行正常（{moment}）"]
    else:
        lines = [f"当前状态：有 {len(active)} 条进行中事件（{moment}）"]
        for index, event in enumerate(active, start=1):
            lines.append(_event_head(index, event))
            lines.extend(_event_details(event))
    # 计划维护不影响整体状态，但订阅者通常想知道后面有没有窗口
    if upcoming:
        lines.append(f"计划维护：{len(upcoming)} 条")
        for event in upcoming:
            # 维护标题为空时同样用占位，保持与事件列表一致
            lines.append(f"· {event.title or '未命名维护'}")
    return "\n".join(lines)


def render_status_reply(snapshot: Snapshot | None, tz: ZoneInfo) -> str:
    """oaistatus 查状态：有快照就复用摘要，没有就提示刚启动。"""
    # 首次采集还没成功时没有可展示的状态
    if snapshot is None:
        return "监控刚启动，还没有数据"
    return render_summary(snapshot, tz)


def render_help(command_name: str) -> str:
    """命令用法；指令名与子命令都从常量取，改名后帮助自动跟着变。"""
    return (
        f"{command_name} —— OpenAI 状态页监控\n"
        f"  {command_name}          查看当前状态\n"
        f"  {command_name} {SUBCOMMAND_ON}       开启本群通知\n"
        f"  {command_name} {SUBCOMMAND_OFF}       关闭本群通知\n"
        f"  {command_name} {SUBCOMMAND_HELP}     显示这条说明"
    )
