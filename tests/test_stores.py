# 数据层 store 测试：在临时目录建真库，验证订阅、变更记录、推送记录与过期清理。
# 不连网络、不导入 astrbot；每个用例用独立的 SQLite 文件，互不干扰。
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from astrbot_plugin_openai_status.data import history_store, subscription_store
from astrbot_plugin_openai_status.data.db import connect, init_db
from astrbot_plugin_openai_status.entity.models import StatusEvent


def utc_days_ago(days: float) -> str:
    """生成指定天数之前的 UTC ISO 时间，用来构造过期或未过期的数据。"""
    moment = datetime.now(timezone.utc) - timedelta(days=days)
    return moment.strftime("%Y-%m-%dT%H:%M:%SZ")


class StoreTestCase(unittest.TestCase):
    """所有 store 用例共用的临时库与连接。"""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.conn = connect(Path(self.temp_dir.name) / "test.db")
        init_db(self.conn)

    def tearDown(self):
        self.conn.close()
        self.temp_dir.cleanup()

    def insert_change(self, fetched_at: str) -> None:
        """直接插一行变更记录，用指定采集时间控制它是否过期。"""
        self.conn.execute(
            "INSERT INTO change_log (change_id, change_type, title, status, fetched_at)"
            " VALUES ('01ABC', 'incident', '事件', 'investigating', ?)",
            (fetched_at,),
        )
        self.conn.commit()

    def insert_push(self, dedup_key: str, created_at: str) -> None:
        """直接插一行推送记录，用指定推送时间控制它是否过期。"""
        self.conn.execute(
            "INSERT INTO push_records"
            " (session, dedup_key, notify_type, message, result, error, created_at)"
            " VALUES ('s', ?, 'changes', '正文', 'ok', '', ?)",
            (dedup_key, created_at),
        )
        self.conn.commit()


class SubscriptionStoreTest(StoreTestCase):
    """订阅表：新增、查询、开、关、页面编辑与删除。"""

    SESSION = "aiocqhttp:GroupMessage:100"

    def test_create_then_query(self):
        """新增成功后能按会话与主键查回同一行。"""
        ok, reason = subscription_store.create(self.conn, self.SESSION, "主群", True)
        self.assertTrue(ok)
        self.assertEqual(reason, "")
        by_session = subscription_store.get_by_session(self.conn, self.SESSION)
        # 查不到说明插入失败，先让用例在这里失败，后面的断言才有对象可看
        assert by_session is not None
        self.assertTrue(by_session.enabled)
        self.assertEqual(by_session.note, "主群")
        by_id = subscription_store.get_by_id(self.conn, by_session.id)
        # 按主键也必须查得到同一条记录，否则新增与查询对不上
        assert by_id is not None
        self.assertEqual(by_id.session, self.SESSION)

    def test_create_rejects_empty_and_duplicate(self):
        """空会话标识与重复会话都要返回失败原因，且不新增行。"""
        ok, reason = subscription_store.create(self.conn, "   ", "空", True)
        self.assertFalse(ok)
        self.assertEqual(reason, "会话标识不能为空")
        subscription_store.create(self.conn, self.SESSION, "主群", True)
        ok, reason = subscription_store.create(self.conn, self.SESSION, "重复", False)
        # 重复时保留原记录，长度仍是 1
        self.assertFalse(ok)
        self.assertEqual(reason, "会话标识已存在")
        self.assertEqual(len(subscription_store.list_subscriptions(self.conn)), 1)

    def test_enable_creates_and_reenables(self):
        """开订阅：新会话新建；停用后再开会保留备注并置为启用。"""
        created, is_new = subscription_store.enable_session(self.conn, self.SESSION, "主群")
        self.assertTrue(is_new)
        self.assertTrue(created.enabled)
        subscription_store.disable_session(self.conn, self.SESSION)
        # 重新启用时不传备注，原备注不能被清空
        reenabled, is_new = subscription_store.enable_session(self.conn, self.SESSION)
        self.assertFalse(is_new)
        self.assertTrue(reenabled.enabled)
        self.assertEqual(reenabled.note, "主群")

    def test_enable_existing_enabled_is_noop(self):
        """原本就启用时只返回原记录，不覆盖备注。"""
        subscription_store.create(self.conn, self.SESSION, "主群", True)
        current, is_new = subscription_store.enable_session(self.conn, self.SESSION, "新备注")
        self.assertFalse(is_new)
        self.assertEqual(current.note, "主群")

    def test_disable(self):
        """关订阅把启用置为停用；没有这条订阅时返回 False。"""
        subscription_store.create(self.conn, self.SESSION, "主群", True)
        self.assertTrue(subscription_store.disable_session(self.conn, self.SESSION))
        current = subscription_store.get_by_session(self.conn, self.SESSION)
        # 关订阅后记录还在，只是启用位变成 0；查不到就没法断言
        assert current is not None
        self.assertFalse(current.enabled)
        self.assertFalse(subscription_store.disable_session(self.conn, "不存在"))

    def test_list_only_enabled(self):
        """只看启用中时，停用的那条不能出现。"""
        subscription_store.create(self.conn, "a", "启用", True)
        subscription_store.create(self.conn, "b", "停用", False)
        enabled = subscription_store.list_subscriptions(self.conn, only_enabled=True)
        self.assertEqual([sub.session for sub in enabled], ["a"])

    def test_update_and_delete(self):
        """页面编辑改备注与开关；删除后按主键查不到，重复删返回 False。"""
        subscription_store.create(self.conn, self.SESSION, "旧备注", True)
        sub = subscription_store.get_by_session(self.conn, self.SESSION)
        # 页面编辑前必须拿到主键；查不到就说明新增没成功，先在这里失败
        assert sub is not None
        self.assertTrue(
            subscription_store.update(self.conn, sub.id, self.SESSION, "新备注", False)
        )
        updated = subscription_store.get_by_id(self.conn, sub.id)
        # 更新后必须还能查到，否则后面的备注与开关断言没有对象
        assert updated is not None
        self.assertEqual(updated.note, "新备注")
        self.assertFalse(updated.enabled)
        # 主键不存在时页面应收到失败，而不是误以为改成功
        self.assertFalse(subscription_store.update(self.conn, 9999, self.SESSION, "无", True))
        self.assertTrue(subscription_store.delete(self.conn, sub.id))
        self.assertIsNone(subscription_store.get_by_id(self.conn, sub.id))
        self.assertFalse(subscription_store.delete(self.conn, sub.id))


class ChangeStoreTest(StoreTestCase):
    """变更记录与推送记录：写入、结果与过期清理。"""

    def make_event(self, change_id: str, status: str) -> StatusEvent:
        """构造一条事件；字段只要够落库即可。"""
        return StatusEvent(
            change_id=change_id,
            change_type="incident",
            title=f"事件{change_id}",
            status=status,
            link=f"https://status.openai.com/incidents/{change_id}",
            components=["Chat Completions"],
            message="We are investigating.",
        )

    def test_record_change_writes_one_row(self):
        """一条变化写一行，ULID、组件与正文原样落库。"""
        event = self.make_event("01M5FD63HHDRPQPM5YMQWJ5HTN", "identified")
        new_id = history_store.record_change(self.conn, event, "2026-10-21T00:00:00Z")
        self.assertIsInstance(new_id, int)
        row = self.conn.execute(
            "SELECT change_id, change_type, title, status, components, message, fetched_at"
            " FROM change_log WHERE id = ?",
            (new_id,),
        ).fetchone()
        self.assertEqual(row["change_id"], "01M5FD63HHDRPQPM5YMQWJ5HTN")
        self.assertEqual(row["change_type"], "incident")
        self.assertEqual(row["title"], "事件01M5FD63HHDRPQPM5YMQWJ5HTN")
        self.assertEqual(row["status"], "identified")
        self.assertEqual(row["components"], '["Chat Completions"]')
        self.assertEqual(row["message"], "We are investigating.")
        self.assertEqual(row["fetched_at"], "2026-10-21T00:00:00Z")

    def test_two_changes_write_two_rows(self):
        """同一轮两条事件变化要落成两行，而不是一行汇总。"""
        first = self.make_event("a1", "monitoring")
        second = self.make_event("a2", "maintenance_complete")
        history_store.record_change(self.conn, first, "2026-10-21T00:00:00Z")
        history_store.record_change(self.conn, second, "2026-10-21T00:00:00Z")
        count = self.conn.execute("SELECT COUNT(*) AS n FROM change_log").fetchone()["n"]
        self.assertEqual(count, 2)

    def test_list_changes_paginates_newest_first(self):
        """按采集时间倒序分页：第一页最新两条，第二页剩下一条。"""
        self.insert_change("2026-10-21T00:00:00Z")
        self.insert_change("2026-10-21T01:00:00Z")
        self.insert_change("2026-10-21T02:00:00Z")
        first_page, total = history_store.list_changes(self.conn, 1, 2)
        self.assertEqual(total, 3)
        self.assertEqual(
            [row["fetched_at"] for row in first_page],
            ["2026-10-21T02:00:00Z", "2026-10-21T01:00:00Z"],
        )
        second_page, _ = history_store.list_changes(self.conn, 2, 2)
        self.assertEqual([row["fetched_at"] for row in second_page], ["2026-10-21T00:00:00Z"])

    def test_list_changes_returns_components_as_list(self):
        """组件名在库里是 JSON 文本，列表接口还原成数组。"""
        event = self.make_event("a1", "investigating")
        history_store.record_change(self.conn, event, "2026-10-21T00:00:00Z")
        rows, _ = history_store.list_changes(self.conn, 1, 10)
        self.assertEqual(rows[0]["components"], ["Chat Completions"])

    def test_list_changes_same_time_orders_by_id_desc(self):
        """同一采集时间写入两行时，后写入的排在前面，顺序稳定。"""
        self.insert_change("2026-10-21T00:00:00Z")
        self.insert_change("2026-10-21T00:00:00Z")
        rows, _ = history_store.list_changes(self.conn, 1, 10)
        first_id = rows[0]["id"]
        second_id = rows[1]["id"]
        assert isinstance(first_id, int) and isinstance(second_id, int)
        self.assertGreater(first_id, second_id)

    def test_list_changes_clamps_page_and_size(self):
        """页码或页大小小于 1 时按 1 处理，不报错也不返回空。"""
        self.insert_change("2026-10-21T00:00:00Z")
        rows, total = history_store.list_changes(self.conn, 0, 0)
        self.assertEqual(total, 1)
        self.assertEqual(len(rows), 1)

    def test_record_push_stores_result_and_error(self):
        """成功与失败各写一行，失败行保留原因与原始报错，时间带 Z。"""
        history_store.record_push(self.conn, "s1", "k1", "changes", "正文", True, "")
        history_store.record_push(
            self.conn, "s2", "k2", "summary", "正文", False, "RuntimeError: boom"
        )
        rows = self.conn.execute(
            "SELECT session, result, error, created_at FROM push_records ORDER BY id"
        ).fetchall()
        self.assertEqual(rows[0]["result"], "ok")
        self.assertEqual(rows[0]["error"], "")
        self.assertEqual(rows[1]["result"], "failed")
        self.assertEqual(rows[1]["error"], "RuntimeError: boom")
        self.assertTrue(rows[1]["created_at"].endswith("Z"))

    def test_purge_expired_removes_old_rows(self):
        """超过保留天数的变更与推送各删一行，未过期的保留，返回删除总数。"""
        self.insert_change(utc_days_ago(31))
        self.insert_change(utc_days_ago(2))
        self.insert_push("old", utc_days_ago(31))
        self.insert_push("new", utc_days_ago(2))
        removed = history_store.purge_expired(self.conn, 30)
        self.assertEqual(removed, 2)
        change_count = self.conn.execute("SELECT COUNT(*) FROM change_log").fetchone()[0]
        push_count = self.conn.execute("SELECT COUNT(*) FROM push_records").fetchone()[0]
        self.assertEqual(change_count, 1)
        self.assertEqual(push_count, 1)

    def test_purge_expired_keeps_rows_inside_retention(self):
        """截止点之前的记录才删，保留期内靠近边界的记录不动。"""
        self.insert_change(utc_days_ago(29.9))
        self.insert_push("inside", utc_days_ago(29.9))
        removed = history_store.purge_expired(self.conn, 30)
        self.assertEqual(removed, 0)

    def test_purge_expired_ignores_non_positive_retention(self):
        """保留天数被改成 0 或负数时不清库，返回 0。"""
        self.insert_change(utc_days_ago(100))
        self.assertEqual(history_store.purge_expired(self.conn, 0), 0)
        self.assertEqual(history_store.purge_expired(self.conn, -5), 0)
        count = self.conn.execute("SELECT COUNT(*) FROM change_log").fetchone()[0]
        self.assertEqual(count, 1)


# 允许直接 python3 tests/test_stores.py 运行本文件
if __name__ == "__main__":
    unittest.main()
