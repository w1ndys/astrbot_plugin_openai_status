# 实体层单测：常量取值、默认时区与四个 dataclass 的构造。
import unittest
from datetime import datetime, timedelta

from astrbot_plugin_openai_status.entity.constants import (
    CLOSED_EVENT_STATUSES,
    COMMAND_NAME,
    DEFAULT_TIMEZONE,
    EVENT_TYPE_LABELS,
    NOTIFY_CHANGES,
    PLUGIN_NAME,
    STATUS_ABNORMAL,
    STATUS_LABELS,
    STATUS_NORMAL,
    SUBCOMMAND_HELP,
    SUBCOMMAND_OFF,
    SUBCOMMAND_ON,
    UPCOMING_EVENT_STATUSES,
)
from astrbot_plugin_openai_status.entity.models import (
    Notification,
    Snapshot,
    StatusEvent,
    Subscription,
)


class ConstantsTest(unittest.TestCase):
    """固定值必须与设计表一致。"""

    def test_plugin_name(self):
        """插件名必须与仓库名一致，AstrBot 靠它找插件与数据目录。"""
        self.assertEqual(PLUGIN_NAME, "astrbot_plugin_openai_status")

    def test_status_values(self):
        """整体状态只有 normal 与 abnormal 两种取值。"""
        self.assertEqual(STATUS_NORMAL, "normal")
        self.assertEqual(STATUS_ABNORMAL, "abnormal")

    def test_notify_changes(self):
        """变化汇总通知只有一个类型值。"""
        self.assertEqual(NOTIFY_CHANGES, "changes")

    def test_status_labels(self):
        """七种事件状态都要有中文映射，含三种维护状态。"""
        self.assertEqual(
            STATUS_LABELS,
            {
                "investigating": "调查中",
                "identified": "已定位",
                "monitoring": "观察中",
                "resolved": "已解决",
                "maintenance_scheduled": "已排期",
                "maintenance_in_progress": "进行中",
                "maintenance_complete": "已完成",
            },
        )

    def test_event_type_labels(self):
        """两类事件都要有中文映射，通知里才标得出故障或计划维护。"""
        self.assertEqual(
            EVENT_TYPE_LABELS,
            {"incident": "故障", "maintenance": "计划维护"},
        )

    def test_closed_event_statuses(self):
        """已解决的故障和已完成的维护算已结束。"""
        self.assertEqual(CLOSED_EVENT_STATUSES, {"resolved", "maintenance_complete"})

    def test_upcoming_event_statuses(self):
        """只有已排期的维护算未来事件，不把整体状态翻成异常。"""
        self.assertEqual(UPCOMING_EVENT_STATUSES, {"maintenance_scheduled"})

    def test_command_name(self):
        """默认指令名固定为 oaistatus，实际生效名由指令管理决定。"""
        self.assertEqual(COMMAND_NAME, "oaistatus")

    def test_subcommand_tokens(self):
        """子命令默认是开 / 关 / 帮助；以后改名只改常量。"""
        self.assertEqual(SUBCOMMAND_ON, "开")
        self.assertEqual(SUBCOMMAND_OFF, "关")
        self.assertEqual(SUBCOMMAND_HELP, "帮助")

    def test_default_timezone_is_utc_plus_8(self):
        """默认回退时区是东八区，没有夏令时偏移。"""
        moment = datetime(2026, 1, 1, 12, 0, tzinfo=DEFAULT_TIMEZONE)
        self.assertEqual(moment.utcoffset(), timedelta(hours=8))


class ModelsTest(unittest.TestCase):
    """四个 dataclass 能按字段构造，值不被改写。"""

    def setUp(self):
        self.event = StatusEvent(
            change_id="01M5FD63HHDRPQPM5YMQWJ5HTN",
            change_type="incident",
            title="测试事件",
            status="investigating",
            link="https://status.openai.com/incidents/01M5FD63HHDRPQPM5YMQWJ5HTN",
            components=["Chat Completions"],
            message="We are investigating.",
        )

    def test_snapshot_holds_status_and_events(self):
        snapshot = Snapshot(
            status=STATUS_ABNORMAL,
            events=[self.event],
            fetched_at="2026-10-21T00:00:00Z",
        )
        self.assertEqual(snapshot.status, STATUS_ABNORMAL)
        self.assertEqual(len(snapshot.events), 1)
        self.assertEqual(snapshot.events[0].change_id, "01M5FD63HHDRPQPM5YMQWJ5HTN")

    def test_event_keeps_components_and_message(self):
        """ULID 原样保存，组件名与最新进展不被改写。"""
        self.assertEqual(self.event.components, ["Chat Completions"])
        self.assertEqual(self.event.message, "We are investigating.")

    def test_normal_snapshot_has_no_events(self):
        snapshot = Snapshot(status=STATUS_NORMAL, events=[], fetched_at="2026-10-21T00:00:00Z")
        self.assertEqual(snapshot.events, [])

    def test_subscription_fields(self):
        subscription = Subscription(
            id=1,
            session="aiocqhttp:GroupMessage:123",
            note="主群",
            enabled=True,
            created_at="2026-10-21T00:00:00Z",
            updated_at="2026-10-21T00:00:00Z",
        )
        self.assertEqual(subscription.session, "aiocqhttp:GroupMessage:123")
        self.assertTrue(subscription.enabled)

    def test_notification_keeps_rendered_message(self):
        notification = Notification(
            notify_type=NOTIFY_CHANGES,
            dedup_key="changes:2026-10-21T00:00:00Z",
            message="API 延迟升高（故障）：观察中",
        )
        self.assertEqual(notification.notify_type, NOTIFY_CHANGES)
        self.assertIn("观察中", notification.message)


if __name__ == "__main__":
    unittest.main()
