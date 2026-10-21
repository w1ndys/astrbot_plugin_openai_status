# 轮询编排单测：假采集、假 Context、假消息链，走真实的 _tick / _dispatch / push_summary。
# 不连网络、不导入 astrbot；每个用例用独立临时库。
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import AsyncMock, patch

from astrbot_plugin_openai_status.business import monitor as monitor_module
from astrbot_plugin_openai_status.business.monitor import Monitor
from astrbot_plugin_openai_status.data.db import connect, init_db, utc_now
from astrbot_plugin_openai_status.data.subscription_store import create
from astrbot_plugin_openai_status.entity.constants import (
    CLOSED_EVENT_STATUSES,
    NOTIFY_CHANGES,
    NOTIFY_SUMMARY,
    STATUS_ABNORMAL,
    STATUS_NORMAL,
    UPCOMING_EVENT_STATUSES,
)
from astrbot_plugin_openai_status.entity.models import (
    MonitorConfig,
    Notification,
    Snapshot,
    StatusEvent,
)


def _config(**overrides: object) -> MonitorConfig:
    """构造默认配置，用例只改自己关心的字段。"""
    values: dict[str, object] = {
        "enabled": True,
        "poll_interval_seconds": 60,
        "notify_enabled": True,
        "history_retention_days": 30,
        "display_timezone": "Asia/Shanghai",
    }
    values.update(overrides)
    return MonitorConfig(**values)  # type: ignore[arg-type]


def _event(change_id: str, status: str) -> StatusEvent:
    """构造一条事件，只填判定与文案用到的字段。"""
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
    """按进行中事件计算整体状态；采集时间用当前 UTC，避免被清理。"""
    unfinished = any(
        event.status not in CLOSED_EVENT_STATUSES
        and event.status not in UPCOMING_EVENT_STATUSES
        for event in events
    )
    return Snapshot(
        status=STATUS_ABNORMAL if unfinished else STATUS_NORMAL,
        events=list(events),
        fetched_at=utc_now(),
    )


def _utc_days_ago(days: int) -> str:
    """生成指定天数之前的 UTC 时间，用来构造过期记录。"""
    moment = datetime.now(timezone.utc) - timedelta(days=days)
    return moment.strftime("%Y-%m-%dT%H:%M:%SZ")


class FakeMessageChain:
    """替代 AstrBot 的消息链，只记录正文。"""

    def __init__(self) -> None:
        self.text = ""

    def message(self, text: str) -> "FakeMessageChain":
        self.text = text
        return self


class FakeContext:
    """替代 AstrBot Context；可指定哪些会话失败或抛异常。"""

    def __init__(self, fail_sessions: set[str] | None = None, result: bool = True) -> None:
        self.fail_sessions = fail_sessions or set()
        self.result = result
        self.sent: list[tuple[str, str]] = []

    async def send_message(self, session: str, chain: FakeMessageChain) -> bool:
        # 指定会话直接返回 False，用来验证失败后继续
        if session in self.fail_sessions:
            return False
        self.sent.append((session, chain.text))
        return self.result


class FakeMonitor(Monitor):
    """把网络采集替换成预设快照，其余方法走真实实现。"""

    def __init__(self, conn, config: MonitorConfig, context: FakeContext) -> None:
        super().__init__(conn, config, context)  # type: ignore[arg-type]
        self.next_snapshot: Snapshot | None = None

    async def _collect(self) -> Snapshot | None:
        return self.next_snapshot


class MonitorTestCase(unittest.IsolatedAsyncioTestCase):
    """所有编排用例共用的临时库与替身。"""

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.conn = connect(Path(self.temp_dir.name) / "test.db")
        init_db(self.conn)
        self.context = FakeContext()
        self.chain_patch = patch.object(monitor_module, "MessageChain", FakeMessageChain)
        self.chain_patch.start()
        self.sleep_patch = patch.object(monitor_module.asyncio, "sleep", new=AsyncMock())
        self.sleep = self.sleep_patch.start()

    def tearDown(self) -> None:
        self.sleep_patch.stop()
        self.chain_patch.stop()
        self.conn.close()
        self.temp_dir.cleanup()

    def make_monitor(self, **overrides: object) -> FakeMonitor:
        """按默认配置建监控；用例可覆盖单个配置项。"""
        return FakeMonitor(self.conn, _config(**overrides), self.context)

    def count(self, table: str) -> int:
        """数一张表的行数，断言写入与清理。"""
        return self.conn.execute(f"SELECT COUNT(*) AS n FROM {table}").fetchone()["n"]


class TickTest(MonitorTestCase):
    """_tick 的采集、差分、落库与推送路径。"""

    async def test_baseline_does_not_record_or_notify(self):
        """首次成功只建基线，不写变更记录、不推送。"""
        monitor = self.make_monitor()
        monitor.next_snapshot = _snapshot(_event("a", "investigating"))
        await monitor._tick()
        self.assertEqual(self.count("change_log"), 0)
        self.assertEqual(self.context.sent, [])
        self.assertIsNotNone(monitor.snapshot())

    async def test_change_writes_records_and_notifies(self):
        """状态变化与新事件各写一行，合成一条消息推给启用订阅。"""
        create(self.conn, "s1", "", True)
        monitor = self.make_monitor()
        monitor.next_snapshot = _snapshot(_event("a", "investigating"))
        await monitor._tick()
        monitor.next_snapshot = _snapshot(_event("a", "identified"), _event("b", "investigating"))
        await monitor._tick()
        self.assertEqual(self.count("change_log"), 2)
        self.assertEqual(len(self.context.sent), 1)
        self.assertIn("检测到 2 条变化", self.context.sent[0][1])
        self.assertEqual(self.count("push_records"), 1)

    async def test_disappeared_event_is_not_notified(self):
        """上一轮有、本轮消失的事件不写记录也不推送。"""
        monitor = self.make_monitor()
        monitor.next_snapshot = _snapshot(_event("a", "investigating"))
        await monitor._tick()
        monitor.next_snapshot = _snapshot()
        await monitor._tick()
        self.assertEqual(self.count("change_log"), 0)
        self.assertEqual(self.context.sent, [])

    async def test_record_failure_keeps_partial_rows_and_skips_push(self):
        """第 2 条记录失败时第 1 条保留，本轮不推送、快照不替换。"""
        create(self.conn, "s1", "", True)
        monitor = self.make_monitor()
        baseline = _snapshot(_event("a", "investigating"))
        monitor.next_snapshot = baseline
        await monitor._tick()
        monitor.next_snapshot = _snapshot(_event("a", "identified"), _event("b", "investigating"))
        real_record_change = monitor_module.record_change
        calls = 0

        def flaky_record_change(conn, event, fetched_at):
            nonlocal calls
            calls += 1
            # 第二条故意失败，第一条照常写入
            if calls == 2:
                raise RuntimeError("db down")
            return real_record_change(conn, event, fetched_at)

        with patch.object(monitor_module, "record_change", side_effect=flaky_record_change):
            await monitor._tick()
        self.assertEqual(self.count("change_log"), 1)
        self.assertEqual(self.context.sent, [])
        self.assertIs(monitor.snapshot(), baseline)

    async def test_notify_disabled_still_records(self):
        """通知关闭时变更记录照写，只是不推送。"""
        create(self.conn, "s1", "", True)
        monitor = self.make_monitor(notify_enabled=False)
        monitor.next_snapshot = _snapshot(_event("a", "investigating"))
        await monitor._tick()
        monitor.next_snapshot = _snapshot(_event("a", "identified"))
        await monitor._tick()
        self.assertEqual(self.count("change_log"), 1)
        self.assertEqual(self.context.sent, [])

    async def test_collect_failure_keeps_snapshot_and_skips_purge(self):
        """采集失败保留旧快照，也不清理过期记录。"""
        self.conn.execute(
            "INSERT INTO change_log (change_id, change_type, title, status, fetched_at)"
            " VALUES ('old', 'incident', '旧记录', 'resolved', ?)",
            (_utc_days_ago(100),),
        )
        self.conn.commit()
        monitor = self.make_monitor()
        baseline = _snapshot(_event("a", "investigating"))
        monitor._snapshot = baseline
        monitor.next_snapshot = None
        await monitor._tick()
        self.assertEqual(self.count("change_log"), 1)
        self.assertIs(monitor.snapshot(), baseline)

    async def test_successful_tick_purges_expired(self):
        """采集成功后按保留天数清理过期记录。"""
        self.conn.execute(
            "INSERT INTO change_log (change_id, change_type, title, status, fetched_at)"
            " VALUES ('old', 'incident', '旧记录', 'resolved', ?)",
            (_utc_days_ago(100),),
        )
        self.conn.commit()
        monitor = self.make_monitor()
        monitor.next_snapshot = _snapshot()
        await monitor._tick()
        self.assertEqual(self.count("change_log"), 0)


class DispatchTest(MonitorTestCase):
    """_dispatch 的逐会话发送、失败继续与间隔。"""

    async def test_sends_to_each_enabled_subscription(self):
        """两个启用订阅各发一次，中间等 1 秒。"""
        create(self.conn, "s1", "", True)
        create(self.conn, "s2", "", True)
        create(self.conn, "s3", "", False)
        monitor = self.make_monitor()
        notification = Notification(NOTIFY_CHANGES, "changes:1", "正文")
        await monitor._dispatch(notification)
        self.assertEqual([session for session, _ in self.context.sent], ["s1", "s2"])
        self.assertEqual(self.count("push_records"), 2)
        self.assertEqual(self.sleep.await_count, 1)

    async def test_failed_session_continues(self):
        """某个会话返回 False 时记失败，继续下一个会话。"""
        create(self.conn, "s1", "", True)
        create(self.conn, "s2", "", True)
        self.context.fail_sessions = {"s1"}
        monitor = self.make_monitor()
        await monitor._dispatch(Notification(NOTIFY_CHANGES, "changes:1", "正文"))
        rows = self.conn.execute(
            "SELECT session, result FROM push_records ORDER BY session"
        ).fetchall()
        self.assertEqual((rows[0]["session"], rows[0]["result"]), ("s1", "failed"))
        self.assertEqual((rows[1]["session"], rows[1]["result"]), ("s2", "ok"))

    async def test_no_enabled_subscription_sends_nothing(self):
        """没有启用订阅时不发送、不写记录、也不等待。"""
        create(self.conn, "s1", "", False)
        monitor = self.make_monitor()
        await monitor._dispatch(Notification(NOTIFY_CHANGES, "changes:1", "正文"))
        self.assertEqual(self.context.sent, [])
        self.assertEqual(self.count("push_records"), 0)
        self.assertEqual(self.sleep.await_count, 0)


class PushSummaryTest(MonitorTestCase):
    """开启订阅时的主动查询与摘要推送。"""

    async def test_notify_disabled_skips_query(self):
        """全局通知关闭时只开订阅，不查也不推，返回 True。"""
        monitor = self.make_monitor(notify_enabled=False)
        self.assertTrue(await monitor.push_summary("s1"))
        self.assertEqual(self.context.sent, [])
        self.assertEqual(self.count("push_records"), 0)
        self.assertIsNone(monitor.snapshot())

    async def test_query_failure_returns_false(self):
        """主动查询失败返回 False，不写推送记录，基线不变。"""
        monitor = self.make_monitor()
        monitor.next_snapshot = None
        self.assertFalse(await monitor.push_summary("s1"))
        self.assertEqual(self.count("push_records"), 0)
        self.assertIsNone(monitor.snapshot())

    async def test_summary_pushed_without_becoming_baseline(self):
        """查询成功就发摘要并写 summary 记录，但不替换监控基线。"""
        monitor = self.make_monitor()
        monitor.next_snapshot = _snapshot()
        self.assertTrue(await monitor.push_summary("s1"))
        self.assertEqual(self.context.sent[0][0], "s1")
        self.assertIn("本群", self.context.sent[0][1])
        row = self.conn.execute("SELECT notify_type, result FROM push_records").fetchone()
        self.assertEqual((row["notify_type"], row["result"]), (NOTIFY_SUMMARY, "ok"))
        self.assertIsNone(monitor.snapshot())

    async def test_group_session_uses_benqun(self):
        """群会话的确认消息用“本群”。"""
        monitor = self.make_monitor()
        monitor.next_snapshot = _snapshot()
        self.assertTrue(await monitor.push_summary("aiocqhttp:GroupMessage:1"))
        self.assertIn("本群", self.context.sent[0][1])
        self.assertNotIn("本会话", self.context.sent[0][1])

    async def test_send_failure_returns_false(self):
        """摘要发送失败返回 False，并写 failed 记录。"""
        self.context.result = False
        monitor = self.make_monitor()
        monitor.next_snapshot = _snapshot()
        self.assertFalse(await monitor.push_summary("s1"))
        row = self.conn.execute("SELECT result FROM push_records").fetchone()
        self.assertEqual(row["result"], "failed")


if __name__ == "__main__":
    unittest.main()
