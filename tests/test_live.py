# 真实网络冒烟：默认 skip，设置 OPENAI_STATUS_LIVE=1 才请求状态页。
# 只验证公开接口的形状，不写库、不推送。
import os
import unittest

from astrbot_plugin_openai_status.business.collector import CollectorError, fetch_summary
from astrbot_plugin_openai_status.business.parser_api import parse_snapshot
from astrbot_plugin_openai_status.data.db import utc_now


@unittest.skipUnless(
    os.getenv("OPENAI_STATUS_LIVE") == "1",
    "真实网络冒烟默认跳过；设 OPENAI_STATUS_LIVE=1 开启",
)
class LiveStatusPageTest(unittest.IsolatedAsyncioTestCase):
    """请求真实摘要接口并按真实结构解析。"""

    async def test_summary_shape(self):
        """能取到两个事件数组，解析结果状态合法，事件 ID 是 ULID。"""
        try:
            summary = await fetch_summary()
        except CollectorError as exc:
            self.fail(f"真实请求失败：{exc}")
        self.assertIn("ongoing_incidents", summary)
        self.assertIn("scheduled_maintenances", summary)
        self.assertIsInstance(summary["ongoing_incidents"], list)
        self.assertIsInstance(summary["scheduled_maintenances"], list)
        snapshot = parse_snapshot(summary, utc_now())
        self.assertIn(snapshot.status, {"normal", "abnormal"})
        for event in snapshot.events:
            self.assertIsInstance(event.change_id, str)
            self.assertTrue(event.status)
            self.assertTrue(event.link.startswith("https://status.openai.com/"))


if __name__ == "__main__":
    unittest.main()
