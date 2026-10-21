# 解析层测试：事件链接、单条事件字段校验与整体快照归一化。
# 不联网、不导入 astrbot；正常态、进行中故障与计划维护都用落盘的实测样本。
import json
import unittest
from copy import deepcopy
from pathlib import Path

from astrbot_plugin_openai_status.business.parser_api import (
    component_name_map,
    event_link,
    parse_event,
    parse_snapshot,
)
from astrbot_plugin_openai_status.entity.constants import (
    STATUS_ABNORMAL,
    STATUS_NORMAL,
    STATUS_PAGE_BASE,
)

# 实测成功响应样本：正常态、进行中故障与计划维护各一份
FIXTURE_DIR = Path(__file__).parent / "fixtures"
NORMAL_FIXTURE = FIXTURE_DIR / "summary_normal.json"
LIVE_FIXTURE = FIXTURE_DIR / "summary_live.json"
MAINTENANCE_FIXTURE = FIXTURE_DIR / "summary_maintenance.json"


def load_summary(path: Path) -> dict:
    """读 fixture 里的 summary 对象。"""
    return json.loads(path.read_text(encoding="utf-8"))["summary"]


class EventLinkTest(unittest.TestCase):
    """事件链接由页面根地址与 ULID 拼成。"""

    def test_link_uses_incidents_path(self):
        """详情页固定在 incidents 路径下，ID 原样出现在末尾。"""
        change_id = "01M5FD63HHDRPQPM5YMQWJ5HTN"
        expected = f"{STATUS_PAGE_BASE}/incidents/{change_id}"
        self.assertEqual(event_link(change_id), expected)


class ComponentNameMapTest(unittest.TestCase):
    """组件 ID 到名称的映射只取合法条目。"""

    def test_maps_id_to_name_and_skips_bad_items(self):
        """缺 ID、缺名称与非对象元素都跳过，不影响合法组件。"""
        names = component_name_map(
            {
                "components": [
                    {"id": "c1", "name": "Chat Completions"},
                    {"id": "", "name": "空 ID"},
                    {"id": "c2", "name": ""},
                    "not-an-object",
                ]
            }
        )
        self.assertEqual(names, {"c1": "Chat Completions"})

    def test_missing_components_is_empty(self):
        """组件表不是数组时返回空表，不抛结构异常。"""
        self.assertEqual(component_name_map({}), {})


class ParseEventTest(unittest.TestCase):
    """单条事件：必填字段校验，组件名与最新正文抽取。"""

    def test_full_item_maps_every_field(self):
        """完整事件原样映射，链接由 ULID 拼出，组件 ID 换成名称。"""
        names = {"c1": "Chat Completions"}
        event = parse_event(
            {
                "id": "01M5FD63HHDRPQPM5YMQWJ5HTN",
                "type": "incident",
                "name": "API 延迟升高",
                "status": "investigating",
                "affected_components": [
                    {"component_id": "c1", "status": "partial_outage"},
                    {"component_id": "unknown", "status": "degraded_performance"},
                ],
                "updates": [
                    {
                        "published_at": "2026-10-21T14:00:00Z",
                        "message_string": "旧进展",
                    },
                    {
                        "published_at": "2026-10-21T14:17:32.465Z",
                        "message_string": "新进展",
                    },
                ],
            },
            names,
        )
        self.assertEqual(event.change_id, "01M5FD63HHDRPQPM5YMQWJ5HTN")
        self.assertEqual(event.change_type, "incident")
        self.assertEqual(event.title, "API 延迟升高")
        self.assertEqual(event.status, "investigating")
        self.assertEqual(event.link, event_link("01M5FD63HHDRPQPM5YMQWJ5HTN"))
        # 组件表里没有的 ID 退回显示 ID，不丢影响范围
        self.assertEqual(event.components, ["Chat Completions", "unknown"])
        self.assertEqual(event.message, "新进展")

    def test_change_id_must_be_non_empty_string(self):
        """数字、空串与缺失的 ID 都算结构异常，并指出字段名。"""
        for bad in (None, "", 123, 12.5):
            with self.subTest(change_id=bad):
                with self.assertRaises(ValueError) as caught:
                    parse_event({"id": bad, "status": "investigating"}, {})
                self.assertIn("id", str(caught.exception))

    def test_status_must_be_non_empty_string(self):
        """状态缺失、空串或非字符串都算结构异常，并指出字段名。"""
        for bad in (None, "", 123):
            with self.subTest(status=bad):
                with self.assertRaises(ValueError) as caught:
                    parse_event({"id": "01ABC", "status": bad}, {})
                self.assertIn("status", str(caught.exception))

    def test_optional_fields_default_to_empty(self):
        """缺标题、类型、组件与更新时仍按正常事件收下。"""
        event = parse_event({"id": "01ABC", "status": "investigating"}, {})
        self.assertEqual(event.title, "")
        self.assertEqual(event.change_type, "")
        self.assertEqual(event.components, [])
        self.assertEqual(event.message, "")


class ParseSnapshotTest(unittest.TestCase):
    """整体快照：合并两个事件数组，按进行中事件与组件状态算整体状态。"""

    def make_event(self, change_id: str, status: str, event_type: str = "incident") -> dict:
        """构造一条最小事件，供结构分支使用。"""
        return {
            "id": change_id,
            "type": event_type,
            "name": f"事件{change_id}",
            "status": status,
            "affected_components": [],
            "updates": [],
        }

    def make_summary(self, ongoing: list, scheduled: list, affected: list | None = None) -> dict:
        """构造最小摘要；组件表留空，避免用例依赖真实组件。"""
        return {
            "components": [],
            "affected_components": affected or [],
            "ongoing_incidents": ongoing,
            "scheduled_maintenances": scheduled,
        }

    def test_normal_fixture(self):
        """实测正常态：没有事件、没有非正常组件。"""
        snapshot = parse_snapshot(load_summary(NORMAL_FIXTURE), "2026-10-21T00:00:00Z")
        self.assertEqual(snapshot.status, STATUS_NORMAL)
        self.assertEqual(snapshot.events, [])
        self.assertEqual(snapshot.fetched_at, "2026-10-21T00:00:00Z")

    def test_live_fixture_maps_incident(self):
        """实测进行中故障：ULID、组件名与最新进展都能解析出来。"""
        snapshot = parse_snapshot(load_summary(LIVE_FIXTURE), "2026-10-21T00:00:00Z")
        self.assertEqual(snapshot.status, STATUS_ABNORMAL)
        self.assertEqual(len(snapshot.events), 1)
        event = snapshot.events[0]
        self.assertEqual(event.change_id, "01M5FD63HHDRPQPM5YMQWJ5HTN")
        self.assertEqual(event.status, "identified")
        self.assertEqual(event.components, ["FedRAMP"])
        self.assertIn("elevated errors", event.message)

    def test_scheduled_maintenance_is_normal(self):
        """实测计划维护：事件保留，但整体状态仍是正常。"""
        snapshot = parse_snapshot(
            load_summary(MAINTENANCE_FIXTURE), "2026-10-21T00:00:00Z"
        )
        self.assertEqual(snapshot.status, STATUS_NORMAL)
        self.assertEqual(len(snapshot.events), 1)
        event = snapshot.events[0]
        self.assertEqual(event.change_type, "maintenance")
        self.assertEqual(event.status, "maintenance_scheduled")
        self.assertTrue(event.link.startswith(f"{STATUS_PAGE_BASE}/incidents/"))

    def test_in_progress_maintenance_is_abnormal(self):
        """进行中的维护计入异常。"""
        summary = self.make_summary(
            [], [self.make_event("m1", "maintenance_in_progress", "maintenance")]
        )
        snapshot = parse_snapshot(summary, "2026-10-21T00:00:00Z")
        self.assertEqual(snapshot.status, STATUS_ABNORMAL)

    def test_completed_maintenance_is_normal(self):
        """已完成的维护留在快照里，但不算异常。"""
        summary = self.make_summary(
            [], [self.make_event("m1", "maintenance_complete", "maintenance")]
        )
        snapshot = parse_snapshot(summary, "2026-10-21T00:00:00Z")
        self.assertEqual(snapshot.status, STATUS_NORMAL)
        self.assertEqual(len(snapshot.events), 1)

    def test_affected_components_make_abnormal(self):
        """没有事件但组件状态非空时，整体按异常处理。"""
        summary = self.make_summary([], [], [{"component_id": "c1", "status": "full_outage"}])
        snapshot = parse_snapshot(summary, "2026-10-21T00:00:00Z")
        self.assertEqual(snapshot.status, STATUS_ABNORMAL)

    def test_duplicate_id_across_arrays_kept_once(self):
        """同一事件同时出现在两个数组时按 ID 去重，只留第一份。"""
        incident = self.make_event("x1", "investigating")
        summary = self.make_summary([incident], [deepcopy(incident)])
        snapshot = parse_snapshot(summary, "2026-10-21T00:00:00Z")
        self.assertEqual(len(snapshot.events), 1)
        self.assertEqual(snapshot.events[0].change_type, "incident")

    def test_ongoing_must_be_list(self):
        """缺 ongoing_incidents 或不是数组：结构异常，消息含字段名。"""
        for data in ({}, {"ongoing_incidents": "x"}):
            with self.subTest(data=data):
                with self.assertRaises(ValueError) as caught:
                    parse_snapshot(data, "2026-10-21T00:00:00Z")
                self.assertIn("ongoing_incidents", str(caught.exception))

    def test_scheduled_must_be_list(self):
        """缺 scheduled_maintenances 或不是数组：结构异常，消息含字段名。"""
        for data in (
            {"ongoing_incidents": []},
            {"ongoing_incidents": [], "scheduled_maintenances": None},
        ):
            with self.subTest(data=data):
                with self.assertRaises(ValueError) as caught:
                    parse_snapshot(data, "2026-10-21T00:00:00Z")
                self.assertIn("scheduled_maintenances", str(caught.exception))

    def test_element_must_be_object(self):
        """元素不是对象：结构异常，消息带下标方便定位。"""
        with self.assertRaises(ValueError) as caught:
            parse_snapshot(self.make_summary(["x"], []), "2026-10-21T00:00:00Z")
        self.assertIn("ongoing_incidents[0]", str(caught.exception))


# 允许直接 python3 tests/test_parser_api.py 运行本文件
if __name__ == "__main__":
    unittest.main()
