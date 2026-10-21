# 业务层变化判定：比较相邻两轮快照，找出需要通知的事件变化。
# 只比较事件状态；事件消失不通知，新出现但已结束的事件也不通知。
from ..entity.constants import CLOSED_EVENT_STATUSES
from ..entity.models import Snapshot, StatusEvent


def detect_event_changes(previous: Snapshot | None, current: Snapshot) -> list[StatusEvent]:
    """按 change_id 找出新出现或状态变化的事件，保持当前快照顺序。"""
    # 首次采集只建基线，没有上一轮可比
    if previous is None:
        return []
    previous_status = {event.change_id: event.status for event in previous.events}
    changes: list[StatusEvent] = []
    seen: set[str] = set()
    for event in current.events:
        # 同一轮重复的 change_id 只认第一条，避免同一条变化被推两次
        if event.change_id in seen:
            continue
        seen.add(event.change_id)
        last_status = previous_status.get(event.change_id)
        # 新出现的事件：已经结束的（resolved / maintenance_complete）不通知
        if last_status is None:
            if event.status in CLOSED_EVENT_STATUSES:
                continue
            changes.append(event)
            continue
        # 状态没变不通知；resolved → investigating 这类回退也算变化
        if last_status != event.status:
            changes.append(event)
    return changes


def changes_key(snapshot: Snapshot) -> str:
    """一轮变化通知的去重键：采集时间保证同一轮只推一次。"""
    return f"changes:{snapshot.fetched_at}"
