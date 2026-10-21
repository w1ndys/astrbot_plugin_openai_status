# 时区解析、渲染与变化汇总单测：合法 IANA、空值、固定偏移写法的回退，本地时间格式与推送版式。
import unittest
from zoneinfo import ZoneInfo

from astrbot_plugin_openai_status.business.text import (
    render_changes,
    render_help,
    render_status_reply,
    render_summary,
    resolve_timezone,
    to_local,
)
from astrbot_plugin_openai_status.entity.constants import (
    DEFAULT_TIMEZONE,
    SUBCOMMAND_HELP,
    SUBCOMMAND_OFF,
    SUBCOMMAND_ON,
)
from astrbot_plugin_openai_status.entity.models import Snapshot, StatusEvent


def _event(
    change_id: str,
    title: str,
    change_type: str,
    status: str,
    components: list[str] | None = None,
    message: str = "",
) -> StatusEvent:
    """构造一条事件，链接按 ID 拼，够文案层使用。"""
    return StatusEvent(
        change_id=change_id,
        change_type=change_type,
        title=title,
        status=status,
        link=f"https://status.openai.com/incidents/{change_id}",
        components=components or [],
        message=message,
    )


class ResolveTimezoneTest(unittest.TestCase):
    """配置值到时区对象的解析规则。"""

    def test_valid_iana_name(self):
        """合法 IANA 名称原样解析。"""
        self.assertEqual(resolve_timezone("Asia/Shanghai"), ZoneInfo("Asia/Shanghai"))

    def test_empty_uses_default(self):
        """空字符串回退默认时区。"""
        self.assertEqual(resolve_timezone("").key, DEFAULT_TIMEZONE.key)

    def test_fixed_offset_falls_back(self):
        """UTC+8 这类固定偏移不是 IANA 名称，回退默认。"""
        self.assertEqual(resolve_timezone("UTC+8").key, DEFAULT_TIMEZONE.key)

    def test_unknown_name_falls_back(self):
        """不存在的时区名回退默认。"""
        self.assertEqual(resolve_timezone("Mars/Olympus").key, DEFAULT_TIMEZONE.key)

    def test_utc_is_valid(self):
        """UTC 是合法名称，不触发回退。"""
        self.assertEqual(resolve_timezone("UTC").key, "UTC")


class ToLocalTest(unittest.TestCase):
    """UTC 采集时间到展示时区的格式。"""

    def test_shanghai(self):
        """UTC 12 点在东八区是 20 点，格式到秒。"""
        self.assertEqual(
            to_local("2026-10-20T12:00:00Z", ZoneInfo("Asia/Shanghai")),
            "2026-10-20 20:00:00",
        )

    def test_new_york_uses_dst(self):
        """纽约 10 月仍在夏令时，UTC 12 点是 08 点。"""
        self.assertEqual(
            to_local("2026-10-20T12:00:00Z", ZoneInfo("America/New_York")),
            "2026-10-20 08:00:00",
        )

    def test_crosses_date(self):
        """跨日时日期跟着时区变，不能只改小时。"""
        self.assertEqual(
            to_local("2026-10-20T23:30:00Z", ZoneInfo("Asia/Shanghai")),
            "2026-10-21 07:30:00",
        )

    def test_utc(self):
        """配置成 UTC 时原样输出，不加偏移后缀。"""
        self.assertEqual(to_local("2026-10-20T12:00:00Z", ZoneInfo("UTC")), "2026-10-20 12:00:00")


class RenderChangesTest(unittest.TestCase):
    """一轮多条变化的汇总版式。"""

    def test_two_changes_with_components_and_message(self):
        """多条变化按顺序编号，附组件、最新进展与链接。"""
        changes = [
            _event(
                "01A",
                "API 延迟升高",
                "incident",
                "investigating",
                components=["Chat Completions", "Responses"],
                message="We are investigating.",
            ),
            _event("01B", "计划维护：API 服务", "maintenance", "maintenance_scheduled"),
        ]
        text = render_changes(changes, "2026-10-20T12:00:00Z", ZoneInfo("Asia/Shanghai"))
        self.assertEqual(
            text,
            "检测到 2 条变化（2026-10-20 20:00:00）\n"
            "1. API 延迟升高（故障 / 调查中）\n"
            "   影响组件：Chat Completions、Responses\n"
            "   最新进展：We are investigating.\n"
            "   https://status.openai.com/incidents/01A\n"
            "2. 计划维护：API 服务（计划维护 / 已排期）\n"
            "   https://status.openai.com/incidents/01B",
        )

    def test_single_change(self):
        """一条变化也走同一版式，数量写 1。"""
        changes = [_event("A", "单条事件", "incident", "monitoring")]
        text = render_changes(changes, "2026-10-20T12:00:00Z", ZoneInfo("Asia/Shanghai"))
        self.assertTrue(text.startswith("检测到 1 条变化（"))

    def test_empty_title_uses_placeholder(self):
        """标题为空时用“未命名事件”占位。"""
        changes = [_event("A", "", "incident", "identified")]
        text = render_changes(changes, "2026-10-20T12:00:00Z", ZoneInfo("Asia/Shanghai"))
        self.assertIn("未命名事件", text)

    def test_unknown_type_and_status_kept_raw(self):
        """映射表里没有的类型/状态原样输出，不丢信息。"""
        changes = [_event("A", "未知事件", "other", "unknown_state")]
        text = render_changes(changes, "2026-10-20T12:00:00Z", ZoneInfo("Asia/Shanghai"))
        self.assertIn("（other / unknown_state）", text)

    def test_long_message_is_trimmed_to_one_line(self):
        """长正文压成一行并截断，避免群消息被刷屏。"""
        changes = [_event("A", "长正文", "incident", "identified", message="x" * 300)]
        text = render_changes(changes, "2026-10-20T12:00:00Z", ZoneInfo("Asia/Shanghai"))
        self.assertIn("最新进展：" + "x" * 200 + "…", text)
        self.assertNotIn("x" * 300, text)


class RenderSummaryTest(unittest.TestCase):
    """订阅开启时的当前状态摘要。"""

    def test_normal_lists_no_events(self):
        """只有已结束事件时按正常处理，不列链接。"""
        snapshot = Snapshot(
            status="normal",
            events=[_event("A", "旧事件", "incident", "resolved")],
            fetched_at="2026-10-20T12:00:00Z",
        )
        text = render_summary(snapshot, ZoneInfo("Asia/Shanghai"))
        self.assertEqual(text, "当前状态：一切运行正常（2026-10-20 20:00:00）")

    def test_upcoming_maintenance_is_listed_after_normal(self):
        """计划维护不影响“一切运行正常”，但单独列出维护标题。"""
        snapshot = Snapshot(
            status="normal",
            events=[
                _event("M", "Scheduled Platform Maintenance", "maintenance", "maintenance_scheduled")
            ],
            fetched_at="2026-10-20T12:00:00Z",
        )
        text = render_summary(snapshot, ZoneInfo("Asia/Shanghai"))
        self.assertEqual(
            text,
            "当前状态：一切运行正常（2026-10-20 20:00:00）\n"
            "计划维护：1 条\n"
            "· Scheduled Platform Maintenance",
        )

    def test_abnormal_lists_active_only(self):
        """异常时列出进行中事件，已结束与计划维护不混进编号列表。"""
        snapshot = Snapshot(
            status="abnormal",
            events=[
                _event(
                    "01A",
                    "API 延迟升高",
                    "incident",
                    "investigating",
                    components=["Chat Completions"],
                    message="We are investigating.",
                ),
                _event("M", "计划维护：API 服务", "maintenance", "maintenance_scheduled"),
                _event("OLD", "旧事件", "incident", "resolved"),
            ],
            fetched_at="2026-10-20T12:00:00Z",
        )
        text = render_summary(snapshot, ZoneInfo("Asia/Shanghai"))
        self.assertEqual(
            text,
            "当前状态：有 1 条进行中事件（2026-10-20 20:00:00）\n"
            "1. API 延迟升高（故障 / 调查中）\n"
            "   影响组件：Chat Completions\n"
            "   最新进展：We are investigating.\n"
            "   https://status.openai.com/incidents/01A\n"
            "计划维护：1 条\n"
            "· 计划维护：API 服务",
        )
        self.assertNotIn("incidents/OLD", text)

    def test_abnormal_without_events(self):
        """只有组件异常、没有事件时给一句不带事件的说明。"""
        snapshot = Snapshot(status="abnormal", events=[], fetched_at="2026-10-20T12:00:00Z")
        text = render_summary(snapshot, ZoneInfo("Asia/Shanghai"))
        self.assertEqual(text, "当前状态：有组件状态异常（2026-10-20 20:00:00）")

    def test_empty_title_uses_placeholder(self):
        """进行中事件标题为空时同样用占位。"""
        snapshot = Snapshot(
            status="abnormal",
            events=[_event("A", "", "incident", "identified")],
            fetched_at="2026-10-20T12:00:00Z",
        )
        text = render_summary(snapshot, ZoneInfo("Asia/Shanghai"))
        self.assertIn("未命名事件", text)


class RenderStatusReplyTest(unittest.TestCase):
    """oaistatus 查状态的回复。"""

    def test_none_snapshot(self):
        """还没采到数据时提示刚启动。"""
        self.assertEqual(
            render_status_reply(None, ZoneInfo("Asia/Shanghai")),
            "监控刚启动，还没有数据",
        )

    def test_normal_reuses_summary(self):
        """有快照时与摘要正文一致。"""
        snapshot = Snapshot(
            status="normal",
            events=[],
            fetched_at="2026-10-20T12:00:00Z",
        )
        expected = render_summary(snapshot, ZoneInfo("Asia/Shanghai"))
        self.assertEqual(render_status_reply(snapshot, ZoneInfo("Asia/Shanghai")), expected)

    def test_abnormal_lists_events(self):
        """非正常时回复里带进行中事件与链接。"""
        snapshot = Snapshot(
            status="abnormal",
            events=[_event("01A", "API 延迟升高", "incident", "investigating")],
            fetched_at="2026-10-20T12:00:00Z",
        )
        text = render_status_reply(snapshot, ZoneInfo("Asia/Shanghai"))
        self.assertIn("incidents/01A", text)
        self.assertIn("调查中", text)


class RenderHelpTest(unittest.TestCase):
    """命令用法说明。"""

    def test_uses_given_command_name(self):
        """指令被改名后，帮助里用实际名字，不写死 oaistatus。"""
        text = render_help("oaimonitor")
        self.assertIn(f"oaimonitor {SUBCOMMAND_ON}", text)
        self.assertNotIn("oaistatus", text)

    def test_lists_status_and_switch_commands(self):
        """帮助里能看到查状态、开、关、帮助四条，子命令取自常量。"""
        text = render_help("oaistatus")
        for part in ("查看当前状态", SUBCOMMAND_ON, SUBCOMMAND_OFF, SUBCOMMAND_HELP):
            self.assertIn(part, text)


if __name__ == "__main__":
    unittest.main()
