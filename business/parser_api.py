# 业务层解析：把摘要接口的 summary 归一化成 Snapshot 与 StatusEvent。
# 本文件不访问数据库，也不发请求；字段不合规时抛 ValueError，由 monitor 记日志。
from ..entity.constants import (
    CLOSED_EVENT_STATUSES,
    STATUS_ABNORMAL,
    STATUS_NORMAL,
    STATUS_PAGE_BASE,
    UPCOMING_EVENT_STATUSES,
)
from ..entity.models import Snapshot, StatusEvent


def event_link(change_id: str) -> str:
    """拼事件详情页地址；故障与计划维护都放在 incidents 路径下。"""
    return f"{STATUS_PAGE_BASE}/incidents/{change_id}"


def component_name_map(summary: dict) -> dict[str, str]:
    """把 summary.components 转成 id -> 名称；组件表缺字段时跳过该条，不影响整轮。"""
    names: dict[str, str] = {}
    components = summary.get("components")
    # 组件表是辅助信息；不是数组时按空表处理，让事件仍能显示 ID
    if not isinstance(components, list):
        return names
    for item in components:
        # 元素不是对象时无法取名称，跳过
        if not isinstance(item, dict):
            continue
        component_id = item.get("id")
        name = item.get("name")
        # 缺 ID 或名称为空的组件没法用于展示，跳过而不是让整轮采集失败
        if isinstance(component_id, str) and component_id and isinstance(name, str) and name:
            names[component_id] = name
    return names


def _affected_component_names(raw: object, names: dict[str, str]) -> list[str]:
    """把 affected_components 里的 ID 换成名称；缺失或非法时按空列表处理。"""
    result: list[str] = []
    # 组件列表是辅助信息；不是数组时不报结构异常
    if not isinstance(raw, list):
        return result
    for item in raw:
        # 元素不是对象时取不到组件 ID，跳过
        if not isinstance(item, dict):
            continue
        component_id = item.get("component_id")
        # 缺组件 ID 的条目无法展示，跳过
        if not isinstance(component_id, str) or not component_id:
            continue
        # 组件表里没有这个 ID 时退回显示 ID，至少不丢信息
        name = names.get(component_id, component_id)
        if name not in result:
            result.append(name)
    return result


def _latest_message(raw: object) -> str:
    """取 updates 里最新一条的正文；没有更新或格式不对时返回空串。"""
    # 更新列表不是数组时没有正文可展示
    if not isinstance(raw, list):
        return ""
    latest = ""
    latest_at = ""
    for update in raw:
        # 单条更新不是对象时跳过
        if not isinstance(update, dict):
            continue
        published_at = update.get("published_at")
        message = update.get("message_string")
        stamp = published_at if isinstance(published_at, str) else ""
        # 时间缺失时用当前顺序兜底，保证后出现的更新覆盖先出现的
        if stamp >= latest_at:
            latest_at = stamp
            latest = message if isinstance(message, str) else ""
    return latest.strip()


def parse_event(item: dict, names: dict[str, str]) -> StatusEvent:
    """解析一条状态事件（含已结束的）；ID 必须是非空字符串、状态必须是非空字符串。"""
    change_id = item.get("id")
    # ID 是 ULID 字符串；数字或空串都不猜着转换，直接按结构异常处理
    if not isinstance(change_id, str) or not change_id:
        raise ValueError(f"事件 id 必须是非空字符串，收到 {type(change_id).__name__}")
    status = item.get("status")
    # 状态为空就判断不了事件是否结束，只能按结构异常处理
    if not isinstance(status, str) or not status:
        raise ValueError(f"事件 status 必须是非空字符串，收到 {type(status).__name__}")
    # 标题与类型只用于展示；缺失或类型不对时收成空串，让文案层决定怎么写
    title = item.get("name")
    if not isinstance(title, str):
        title = ""
    change_type = item.get("type")
    if not isinstance(change_type, str):
        change_type = ""
    return StatusEvent(
        change_id=change_id,
        change_type=change_type,
        title=title,
        status=status,
        link=event_link(change_id),
        components=_affected_component_names(item.get("affected_components"), names),
        message=_latest_message(item.get("updates")),
    )


def parse_snapshot(summary: dict, fetched_at: str) -> Snapshot:
    """把 summary 解析成快照；两个事件数组都必须存在。"""
    ongoing = summary.get("ongoing_incidents")
    # 缺字段或不是数组说明接口形状变了，抛 ValueError 让 monitor 记结构异常
    if not isinstance(ongoing, list):
        raise ValueError("ongoing_incidents 必须是数组")
    scheduled = summary.get("scheduled_maintenances")
    # 计划维护也是事件来源；字段缺失同样按结构异常处理
    if not isinstance(scheduled, list):
        raise ValueError("scheduled_maintenances 必须是数组")
    names = component_name_map(summary)
    events: list[StatusEvent] = []
    seen: set[str] = set()
    for field, items in (("ongoing_incidents", ongoing), ("scheduled_maintenances", scheduled)):
        for index, item in enumerate(items):
            # 元素不是对象时带上下标，日志里能直接定位是第几条
            if not isinstance(item, dict):
                raise ValueError(f"{field}[{index}] 必须是对象")
            event = parse_event(item, names)
            # 同一事件可能同时出现在两个数组里，按 ID 去重只留第一条
            if event.change_id in seen:
                continue
            seen.add(event.change_id)
            events.append(event)
    # 只有进行中的事件算异常；已结束与只是排期的维护都不翻整体状态
    abnormal = False
    for event in events:
        # 跳过已结束和尚未开始的维护
        if event.status in CLOSED_EVENT_STATUSES or event.status in UPCOMING_EVENT_STATUSES:
            continue
        abnormal = True
        break
    # affected_components 非空说明有组件状态不对，作为整体状态的辅助判据
    affected = summary.get("affected_components")
    if isinstance(affected, list) and affected:
        abnormal = True
    status = STATUS_ABNORMAL if abnormal else STATUS_NORMAL
    return Snapshot(status=status, events=events, fetched_at=fetched_at)
