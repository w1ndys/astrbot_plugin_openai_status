# 脚手架自检：确认仓库骨架、插件元数据与配置 schema 已落盘且取值符合规格。
import json
import unittest
from pathlib import Path

# 仓库根目录：tests/ 的上一级，下面所有路径都以它为基准
REPO_ROOT = Path(__file__).resolve().parents[1]
# 插件配置文件：AstrBot 用它渲染官方配置页
CONF_SCHEMA = REPO_ROOT / "_conf_schema.json"
# 插件元数据：AstrBot 靠它识别插件名称与版本
METADATA = REPO_ROOT / "metadata.yaml"


class ScaffoldTest(unittest.TestCase):
    """检查骨架文件与字段。"""

    def test_required_packages_exist(self):
        """四个分层目录都必须是可导入的包。"""
        # 缺 __init__.py 时目录不是包，后续测试与运行会导入失败
        for name in ("entity", "data", "business", "tests"):
            package_init = REPO_ROOT / name / "__init__.py"
            self.assertTrue(package_init.is_file(), f"{name}/__init__.py 缺失")

    def test_metadata_declares_plugin_identity(self):
        """元数据必须写明插件名、版本与 AstrBot 版本要求。"""
        text = METADATA.read_text(encoding="utf-8")
        # 名称必须与仓库名一致，AstrBot 按它定位插件与数据目录
        self.assertIn("name: astrbot_plugin_openai_status", text)
        # 版本与需求 11.2 的初始版本一致
        self.assertIn("version: 0.1.0", text)
        # 没有这一行 AstrBot 无法判断兼容范围
        self.assertIn("astrbot_version:", text)

    def test_conf_schema_fields_match_design(self):
        """五个配置字段的类型与默认值必须与设计表一致。"""
        schema = json.loads(CONF_SCHEMA.read_text(encoding="utf-8"))
        expected = {
            "enabled": ("bool", False),
            "poll_interval_seconds": ("int", 60),
            "notify_enabled": ("bool", True),
            "history_retention_days": ("int", 30),
            "display_timezone": ("string", "Asia/Shanghai"),
        }
        for key, (kind, default) in expected.items():
            field = schema.get(key)
            # 缺字段会让配置页少一项，运行时也读不到默认值
            self.assertIsNotNone(field, f"缺少字段 {key}")
            self.assertEqual(field["type"], kind)
            self.assertEqual(field["default"], default)

    def test_conf_schema_ranges_match_requirements(self):
        """两个整数字段的滑块上下限必须与需求约定的取值范围一致。"""
        schema = json.loads(CONF_SCHEMA.read_text(encoding="utf-8"))
        ranges = {
            "poll_interval_seconds": (30, 3600),
            "history_retention_days": (1, 365),
        }
        for key, (low, high) in ranges.items():
            field = schema[key]
            # 上限或下限错位会让轮询间隔或留存天数落到非法区间
            self.assertEqual(field.get("slider", {}).get("min"), low)
            self.assertEqual(field.get("slider", {}).get("max"), high)

    def test_display_timezone_hint_explains_iana_rule(self):
        """时区提示必须写明 IANA 规则，并排除固定偏移写法。"""
        schema = json.loads(CONF_SCHEMA.read_text(encoding="utf-8"))
        hint = schema["display_timezone"]["hint"]
        # 用户照着提示填，才不会在页面保存时被拒
        self.assertIn("IANA", hint)
        self.assertIn("Asia/Shanghai", hint)
        self.assertIn("UTC+8", hint)


# 允许直接 python3 tests/test_scaffold.py 运行本文件
if __name__ == "__main__":
    unittest.main()
