# 事件变化判定单测：新出现、状态变化、消失、已结束与重复 ID 的边界。
import unittest

from astrbot_plugin_openai_status.business.detector import (
    changes_key,
    detect_event_changes,
)
from astrbot_plugin_openai_status.entity.models import Snapshot, StatusEvent


def _event(change_id: str, status: str) -> StatusEvent:
    """构造一条事件，只填判定需要的字段。"""
    return StatusEvent(
        change_id=change_id,
        change_type="incident",
        title=f"事件{change_id}",
        status=status,
        link=f"https://status.openai.com/incidents/{change_id}",
        components=[],
        message="",
    )


def _snapshot(*events: StatusEvent) -> Snapshot:
    """构造快照；判定只读 events，整体状态固定 normal。"""
    return Snapshot(status="normal", events=list(events), fetched_at="2026-10-21T00:00:00Z")


class DetectEventChangesTest(unittest.TestCase):
    """前后两轮快照的差分规则。"""

    def test_no_previous_returns_empty(self):
        """首次采集没有上一轮，返回空列表。"""
        self.assertEqual(detect_event_changes(None, _snapshot(_event("a", "investigating"))), [])

    def test_changes_key_uses_fetched_at(self):
        """一轮通知一个键，键里带该轮采集时间。"""
        snapshot = _snapshot(_event("a", "investigating"))
        self.assertEqual(changes_key(snapshot), "changes:2026-10-21T00:00:00Z")

    def test_new_open_event_is_change(self):
        """新出现且未结束的事件算一条变化。"""
        current = _snapshot(_event("a", "investigating"))
        changes = detect_event_changes(_snapshot(), current)
        self.assertEqual([event.change_id for event in changes], ["a"])

    def test_new_closed_event_is_not_change(self):
        """新出现就是已解决 / 已完成的故障不通知。"""
        for closed in ("resolved", "maintenance_complete"):
            current = _snapshot(_event("a", closed))
            self.assertEqual(detect_event_changes(_snapshot(), current), [])

    def test_new_upcoming_maintenance_is_change(self):
        """新出现的计划维护要通知，即使整体状态仍正常。"""
        current = _snapshot(_event("m", "maintenance_scheduled"))
        changes = detect_event_changes(_snapshot(), current)
        self.assertEqual([event.change_id for event in changes], ["m"])

    def test_same_status_is_not_change(self):
        """两轮状态相同不产生变化。"""
        previous = _snapshot(_event("a", "monitoring"))
        current = _snapshot(_event("a", "monitoring"))
        self.assertEqual(detect_event_changes(previous, current), [])

    def test_status_change_is_change(self):
        """同一事件状态变化算一条变化。"""
        previous = _snapshot(_event("a", "investigating"))
        current = _snapshot(_event("a", "identified"))
        self.assertEqual(len(detect_event_changes(previous, current)), 1)

    def test_closed_to_investigating_is_change(self):
        """resolved 之后又回到 investigating，仍算变化。"""
        previous = _snapshot(_event("a", "resolved"))
        current = _snapshot(_event("a", "investigating"))
        self.assertEqual(len(detect_event_changes(previous, current)), 1)

    def test_disappeared_event_is_not_change(self):
        """上一轮有、本轮消失的事件不通知。"""
        previous = _snapshot(_event("a", "investigating"))
        self.assertEqual(detect_event_changes(previous, _snapshot()), [])

    def test_duplicate_change_id_in_one_round_counts_once(self):
        """同一轮重复 ID 只认第一条，避免同一条变化推两次。"""
        current = _snapshot(_event("a", "investigating"), _event("a", "identified"))
        changes = detect_event_changes(_snapshot(), current)
        self.assertEqual(len(changes), 1)
        self.assertEqual(changes[0].status, "investigating")

    def test_order_follows_current_snapshot(self):
        """多条变化按当前快照顺序返回。"""
        previous = _snapshot(_event("a", "investigating"), _event("b", "investigating"))
        current = _snapshot(_event("b", "identified"), _event("a", "identified"))
        changes = detect_event_changes(previous, current)
        self.assertEqual([event.change_id for event in changes], ["b", "a"])


if __name__ == "__main__":
    unittest.main()
