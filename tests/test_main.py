# 入口层测试：先注入最小 astrbot 替身，再导入 main，覆盖命令分支与 Web API 校验。
# 替身只实现被调用的接口；AstrBot 真实接口变化时这里需要同步。
import logging
import sys
import tempfile
import types
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import AsyncMock, patch

from astrbot_plugin_openai_status.data import history_store, subscription_store
from astrbot_plugin_openai_status.entity.models import Snapshot, StatusEvent


class FakeFilter:
    """替代 filter，command 装饰器原样返回函数。"""

    def command(self, *_args, **_kwargs):
        def decorator(func):
            return func

        return decorator


class FakeEvent:
    """替代 AstrMessageEvent，只提供命令处理用到的字段。"""

    def __init__(self, message_str: str, session: str) -> None:
        self.message_str = message_str
        self.unified_msg_origin = session
        self.stopped = False

    def plain_result(self, text: str) -> str:
        return text

    def stop_event(self) -> None:
        self.stopped = True


class FakeContext:
    """替代 Context，记录注册的路由，并可挂一个假 aiocqhttp 平台。"""

    def __init__(self) -> None:
        self.routes: list[tuple[str, object, list[str], str]] = []
        self.platform = None

    def register_web_api(self, route, handler, methods, desc) -> None:
        self.routes.append((route, handler, methods, desc))

    def get_platform(self, name: str):
        return self.platform if name == "aiocqhttp" else None


class FakeBot:
    """替代 aiocqhttp 的 bot，只实现 get_group_info。"""

    async def call_action(self, action: str, **kwargs):
        if action == "get_group_info":
            return {"group_id": kwargs.get("group_id"), "group_name": "测试群"}
        raise RuntimeError(f"未实现 {action}")


class FakePlatform:
    """替代 aiocqhttp 适配器，提供 meta 与 bot。"""

    def __init__(self, platform_id: str = "aiocqhttp") -> None:
        self.platform_id = platform_id
        self.bot = FakeBot()

    def meta(self):
        return types.SimpleNamespace(id=self.platform_id, name="aiocqhttp")


class FakeStar:
    """替代 Star，提供 context 与 logger。"""

    def __init__(self, context, config=None) -> None:
        self.context = context
        self.logger = logging.getLogger("test-plugin")


class FakeConfig(dict):
    """替代 AstrBotConfig，保存时合并并记录调用。"""

    def __init__(self, values=None) -> None:
        super().__init__(values or {})
        self.saved: list[dict] = []

    def save_config(self, replace_config=None) -> None:
        if replace_config:
            self.update(replace_config)
        self.saved.append(dict(self))


class FakeQuery:
    """替代 request.query，支持 type=int 的取值。"""

    def __init__(self) -> None:
        self.params: dict[str, str] = {}

    def get(self, name, default=None, type=None):
        value = self.params.get(name, default)
        if type is None or value is default:
            return value
        try:
            return type(value)
        except (TypeError, ValueError):
            return default


class FakeRequest:
    """替代 request 代理，用例直接改 payload 与 query。"""

    def __init__(self) -> None:
        self.payload: dict = {}
        self.query = FakeQuery()

    async def json(self, default=None):
        return self.payload


class FakeMessageChain:
    """替代 MessageChain，只保存正文。"""

    def message(self, text: str) -> "FakeMessageChain":
        self.text = text
        return self


class FakeMessageSession:
    """替代 MessageSession，只校验三段与消息类型。"""

    @staticmethod
    def from_str(value: str) -> "FakeMessageSession":
        parts = value.split(":", 2)
        if len(parts) != 3 or not all(parts):
            raise ValueError("bad session")
        if parts[1] not in ("GroupMessage", "FriendMessage"):
            raise ValueError("bad type")
        return FakeMessageSession()


def _install_astrbot_fakes() -> None:
    """把 astrbot 的最小模块树塞进 sys.modules，供 main 导入。"""
    astrbot = types.ModuleType("astrbot")
    api = types.ModuleType("astrbot.api")
    api.logger = logging.getLogger("astrbot")
    event = types.ModuleType("astrbot.api.event")
    event.AstrMessageEvent = FakeEvent
    event.MessageChain = FakeMessageChain
    event.filter = FakeFilter()
    star = types.ModuleType("astrbot.api.star")
    star.Context = FakeContext
    star.Star = FakeStar
    web = types.ModuleType("astrbot.api.web")
    web.request = FakeRequest()

    def json_response(data=None, **kwargs):
        return {"data": data, "status_code": kwargs.get("status_code", 200)}

    def error_response(message, status_code=400, data=None, **kwargs):
        return {
            "status": "error",
            "message": message,
            "data": data,
            "status_code": status_code,
        }

    web.json_response = json_response
    web.error_response = error_response

    core = types.ModuleType("astrbot.core")
    platform = types.ModuleType("astrbot.core.platform")
    message_session = types.ModuleType("astrbot.core.platform.message_session")
    message_session.MessageSession = FakeMessageSession

    astrbot.api = api
    api.event = event
    api.star = star
    api.web = web
    astrbot.core = core
    core.platform = platform
    platform.message_session = message_session
    sys.modules.update(
        {
            "astrbot": astrbot,
            "astrbot.api": api,
            "astrbot.api.event": event,
            "astrbot.api.star": star,
            "astrbot.api.web": web,
            "astrbot.core": core,
            "astrbot.core.platform": platform,
            "astrbot.core.platform.message_session": message_session,
        }
    )


_install_astrbot_fakes()

from astrbot_plugin_openai_status import main as main_module  # noqa: E402


DEFAULT_CONFIG = {
    "enabled": False,
    "poll_interval_seconds": 60,
    "notify_enabled": True,
    "history_retention_days": 30,
    "display_timezone": "Asia/Shanghai",
}


class PluginTestCase(unittest.IsolatedAsyncioTestCase):
    """共用临时库、假配置与假请求。"""

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "test.db"
        self.context = FakeContext()
        self.config = FakeConfig(DEFAULT_CONFIG)
        self.path_patch = patch.object(main_module, "get_db_path", return_value=self.db_path)
        self.path_patch.start()
        self.plugin = main_module.Plugin(self.context, self.config)
        self.web = sys.modules["astrbot.api.web"]
        self.web.request.payload = {}
        self.web.request.query.params = {}

    def tearDown(self) -> None:
        self.path_patch.stop()
        self.plugin.conn.close()
        self.temp_dir.cleanup()

    def set_enabled(self, enabled: bool, notify: bool = True) -> None:
        """改监控总开关，模拟页面保存后的内存配置。"""
        self.plugin.monitor.config = replace(
            self.plugin.monitor.config, enabled=enabled, notify_enabled=notify
        )


class RouteTest(PluginTestCase):
    """构造时可以注册全部路由。"""

    def test_registers_nine_routes(self):
        """9 条 Web API 全部登记，路径都带插件名前缀。"""
        self.assertEqual(len(self.context.routes), 9)
        for route, _, _, _ in self.context.routes:
            self.assertTrue(route.startswith("/astrbot_plugin_openai_status/"))


class SettingsTest(PluginTestCase):
    """读写配置的校验与热更新。"""

    async def test_invalid_timezone_returns_400(self):
        """IANA 名称非法时整单 400，配置不变。"""
        self.web.request.payload = {"display_timezone": "UTC+8"}
        result = await self.plugin.page_save_settings()
        self.assertEqual(result["status_code"], 400)
        self.assertEqual(self.plugin.monitor.config.display_timezone, "Asia/Shanghai")

    async def test_valid_settings_saved_and_applied(self):
        """合法值写入配置、替换内存配置并重启轮询。"""
        self.web.request.payload = {
            "enabled": False,
            "poll_interval_seconds": 120,
            "notify_enabled": False,
            "history_retention_days": 7,
            "display_timezone": "UTC",
        }
        result = await self.plugin.page_save_settings()
        self.assertEqual(result["status_code"], 200)
        self.assertEqual(self.plugin.monitor.config.poll_interval_seconds, 120)
        self.assertEqual(self.plugin.monitor.config.display_timezone, "UTC")
        self.assertTrue(self.config.saved)

    async def test_status_hides_snapshot_when_disabled(self):
        """总开关关闭时状态接口不返回旧快照。"""
        self.set_enabled(False)
        result = await self.plugin.page_get_status()
        self.assertEqual(result["data"], {"enabled": False, "snapshot": None})

    async def test_status_includes_components_and_message(self):
        """状态接口把组件名与最新进展一起返回给页面。"""
        self.set_enabled(True)
        self.plugin.monitor._snapshot = Snapshot(
            status="abnormal",
            events=[
                StatusEvent(
                    change_id="01ABC",
                    change_type="incident",
                    title="事件",
                    status="investigating",
                    link="https://status.openai.com/incidents/01ABC",
                    components=["Chat Completions"],
                    message="We are investigating.",
                )
            ],
            fetched_at="2026-10-21T00:00:00Z",
        )
        result = await self.plugin.page_get_status()
        event = result["data"]["snapshot"]["events"][0]
        self.assertEqual(event["components"], ["Chat Completions"])
        self.assertEqual(event["message"], "We are investigating.")
        self.assertEqual(event["change_id"], "01ABC")


class SubscriptionApiTest(PluginTestCase):
    """页面新增、编辑、删除订阅。"""

    def setUp(self) -> None:
        super().setUp()
        # 新订阅要按平台实例 id 拼 UMO，测试里挂一个假平台
        self.context.platform = FakePlatform()

    async def test_create_rejects_bad_group_id(self):
        """群号不是纯数字时返回 400。"""
        self.web.request.payload = {"group_id": "abc"}
        result = await self.plugin.page_create_subscription()
        self.assertEqual(result["status_code"], 400)

    async def test_create_rejects_duplicate(self):
        """同一群号重复新增返回 400。"""
        subscription_store.create(self.plugin.conn, "aiocqhttp:GroupMessage:1", "", True)
        self.web.request.payload = {"group_id": "1"}
        result = await self.plugin.page_create_subscription()
        self.assertEqual(result["status_code"], 400)

    async def test_update_missing_returns_404(self):
        """编辑不存在的订阅返回 404。"""
        self.web.request.payload = {"note": "x"}
        result = await self.plugin.page_update_subscription("99")
        self.assertEqual(result["status_code"], 404)

    async def test_delete_missing_returns_404(self):
        """删除不存在的订阅返回 404。"""
        result = await self.plugin.page_delete_subscription("99")
        self.assertEqual(result["status_code"], 404)


class GroupNameTest(PluginTestCase):
    """按群号取群名。"""

    async def test_get_group_name(self):
        """群号合法时返回 aiocqhttp 的群名。"""
        self.context.platform = FakePlatform()
        self.web.request.query.params = {"group_id": "123"}
        result = await self.plugin.page_get_group_name()
        self.assertEqual(result["data"], {"group_name": "测试群"})

    async def test_bad_group_id_returns_400(self):
        """群号不是纯数字时返回 400。"""
        self.web.request.query.params = {"group_id": "abc"}
        result = await self.plugin.page_get_group_name()
        self.assertEqual(result["status_code"], 400)

    async def test_no_platform_returns_400(self):
        """没有 aiocqhttp 平台时返回 400。"""
        self.web.request.query.params = {"group_id": "123"}
        result = await self.plugin.page_get_group_name()
        self.assertEqual(result["status_code"], 400)


class PlatformIdTest(PluginTestCase):
    """平台 id 不是 aiocqhttp 时，会话前缀要自适应。"""

    def test_normalize_napcat_session(self):
        """aiocqhttp 前缀改写成实际平台 id。"""
        self.context.platform = FakePlatform("napcat")
        session = self.plugin._normalize_session("aiocqhttp:GroupMessage:1")
        self.assertEqual(session, "napcat:GroupMessage:1")

    def test_migrates_existing_subscription(self):
        """启动迁移把旧订阅前缀改成当前平台 id。"""
        self.context.platform = FakePlatform("napcat")
        subscription_store.create(self.plugin.conn, "aiocqhttp:GroupMessage:2", "旧备注", True)
        self.plugin._migrate_sessions()
        stored = subscription_store.get_by_session(self.plugin.conn, "napcat:GroupMessage:2")
        self.assertIsNotNone(stored)

    async def test_create_uses_platform_id(self):
        """页面新增订阅时用平台 id 拼 UMO。"""
        self.context.platform = FakePlatform("napcat")
        self.web.request.payload = {"group_id": "3"}
        result = await self.plugin.page_create_subscription()
        self.assertEqual(result["status_code"], 200)
        stored = subscription_store.get_by_session(self.plugin.conn, "napcat:GroupMessage:3")
        self.assertIsNotNone(stored)


class CommandTest(PluginTestCase):
    """oaistatus 命令分支。"""

    def setUp(self) -> None:
        super().setUp()
        self.context.platform = FakePlatform()

    async def collect(self, sub: str, message: str = "oaistatus 帮助") -> list[str]:
        """跑一次命令，收集所有回复文本。"""
        event = FakeEvent(message, "aiocqhttp:GroupMessage:1")
        return [item async for item in self.plugin.oaistatus(event, sub)]

    async def test_command_stops_llm(self):
        """命令处理完调用 stop_event，阻止继续进入 LLM。"""
        event = FakeEvent("oaistatus 帮助", "aiocqhttp:GroupMessage:1")
        _ = [item async for item in self.plugin.oaistatus(event, "帮助")]
        self.assertTrue(event.stopped)

    async def test_help_uses_actual_command_name(self):
        """指令被改名后，帮助使用实际 token。"""
        messages = await self.collect("帮助", "oaihelp 帮助")
        self.assertIn("oaihelp", messages[0])
        self.assertNotIn("oaistatus", messages[0])

    async def test_status_when_monitor_disabled(self):
        """监控关闭时查状态回“监控已关闭”。"""
        self.set_enabled(False)
        messages = await self.collect("", "oaistatus")
        self.assertEqual(messages, ["监控已关闭。"])

    async def test_on_when_global_disabled_only_writes_subscription(self):
        """全局关闭时开启只写订阅，不查询也不推送。"""
        self.set_enabled(False)
        messages = await self.collect("开", "oaistatus 开")
        self.assertEqual(messages, ["已开启，全局通知关闭，暂不推送。"])
        stored = subscription_store.get_by_session(
            self.plugin.conn, "aiocqhttp:GroupMessage:1"
        )
        self.assertIsNotNone(stored)
        # 命令开启时备注为空，应自动拉群名写库
        self.assertEqual(stored.note, "测试群")

    async def test_on_success_has_no_extra_reply(self):
        """开启成功时确认消息就是回复，命令不再多发一条。"""
        self.set_enabled(True)
        self.plugin.monitor.push_summary = AsyncMock(return_value=True)
        messages = await self.collect("开", "oaistatus 开")
        self.assertEqual(messages, [])

    async def test_on_query_failure_replies(self):
        """主动查询失败时回“已开启，但暂时取不到状态”。"""
        self.set_enabled(True)
        self.plugin.monitor.push_summary = AsyncMock(return_value=False)
        messages = await self.collect("开", "oaistatus 开")
        self.assertEqual(messages, ["已开启，但暂时取不到状态。"])

    async def test_private_chat_is_ignored(self):
        """私聊发送命令不回复，也不写订阅。"""
        event = FakeEvent("oaistatus 开", "aiocqhttp:FriendMessage:1")
        messages = [item async for item in self.plugin.oaistatus(event, "开")]
        self.assertEqual(messages, [])
        stored = subscription_store.get_by_session(
            self.plugin.conn, "aiocqhttp:FriendMessage:1"
        )
        self.assertIsNone(stored)

    async def test_off_without_subscription(self):
        """从没订阅过时关闭回“本群还没有订阅”。"""
        messages = await self.collect("关", "oaistatus 关")
        self.assertEqual(messages, ["本群还没有订阅。"])


class ChangesApiTest(PluginTestCase):
    """变更记录分页参数保护。"""

    async def test_clamps_page_and_size(self):
        """页码与页大小小于 1 时回到默认值。"""
        event = StatusEvent(
            change_id="01ABC",
            change_type="incident",
            title="事件",
            status="investigating",
            link="https://status.openai.com/incidents/01ABC",
            components=[],
            message="",
        )
        history_store.record_change(self.plugin.conn, event, "2026-10-21T00:00:00Z")
        self.web.request.query.params = {"page": "0", "size": "0"}
        result = await self.plugin.page_list_changes()
        self.assertEqual(result["data"]["page"], 1)
        self.assertEqual(result["data"]["size"], 20)
        self.assertEqual(result["data"]["total"], 1)


if __name__ == "__main__":
    unittest.main()
