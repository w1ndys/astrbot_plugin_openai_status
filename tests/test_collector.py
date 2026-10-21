# 采集层测试：接口地址、超时配置与摘要接口的失败分类。
# 本机没装 aiohttp；用例装一个最小替身模块，只验证本模块的分支，不发真实请求。
import json
import sys
import types
import unittest
from pathlib import Path

from astrbot_plugin_openai_status.business.collector import (
    CollectorError,
    api_url,
    fetch_summary,
    make_timeout,
)
from astrbot_plugin_openai_status.entity.constants import API_BASE, REQUEST_TIMEOUT_SECONDS

# 实测成功响应样本，成功路径直接用它构造响应体
FIXTURE = Path(__file__).parent / "fixtures" / "summary_live.json"


class FakeClientError(Exception):
    """替身 aiohttp.ClientError，用来模拟连接失败。"""


class FakeTimeout:
    """替身 aiohttp.ClientTimeout，只保留 total 供断言。"""

    def __init__(self, total=None):
        self.total = total


class FakeResponse:
    """替身响应：给出状态、JSON 结果或解析异常。"""

    def __init__(self, status, payload=None, body="", json_error=None):
        self.status = status
        self.payload = payload
        self.body = body
        self.json_error = json_error

    async def json(self):
        # 模拟 200 但正文不是合法 JSON：抛 ValueError 让采集函数归类
        if self.json_error is not None:
            raise self.json_error
        return self.payload

    async def text(self):
        return self.body


class FakeRequest:
    """替身请求：只实现 async with 需要的两个方法。"""

    def __init__(self, response):
        self.response = response

    async def __aenter__(self):
        return self.response

    async def __aexit__(self, *args):
        return False


class FakeSession:
    """替身会话：记录请求地址与头，必要时在发请求处抛错。"""

    def __init__(self, response=None, error=None, timeout=None):
        self.response = response
        self.error = error
        self.timeout = timeout
        self.request_url = ""
        self.request_headers = None

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    def get(self, url, headers=None):
        self.request_url = url
        self.request_headers = headers
        # 模拟连接失败：真正的 aiohttp 也在这里抛 ClientError
        if self.error is not None:
            raise self.error
        return FakeRequest(self.response)


def install_fake_aiohttp(response=None, error=None):
    """把最小替身装进 sys.modules，返回本次创建的会话列表供断言。"""
    sessions = []
    module = types.ModuleType("aiohttp")
    setattr(module, "ClientError", FakeClientError)
    setattr(module, "ClientTimeout", FakeTimeout)

    def client_session(*, timeout=None):
        session = FakeSession(response=response, error=error, timeout=timeout)
        sessions.append(session)
        return session

    setattr(module, "ClientSession", client_session)
    sys.modules["aiohttp"] = module
    return sessions


class FakeAiohttpTestCase(unittest.IsolatedAsyncioTestCase):
    """需要 aiohttp 的用例共用：装替身，跑完恢复原来的模块状态。"""

    def setUp(self):
        self.saved_aiohttp = sys.modules.get("aiohttp")

    def tearDown(self):
        # 原来没有就删掉替身，原来有就还原，避免影响其它用例
        if self.saved_aiohttp is None:
            sys.modules.pop("aiohttp", None)
        else:
            sys.modules["aiohttp"] = self.saved_aiohttp


class ApiUrlTest(unittest.TestCase):
    """接口地址由代理根地址与传入路径拼成。"""

    def test_summary_url_is_proxy_root(self):
        """摘要接口就是代理根地址，末尾没有多余斜杠。"""
        self.assertEqual(api_url(""), API_BASE)

    def test_path_is_appended_without_rewriting(self):
        """函数只做拼接；调用方给的路径原样出现在末尾。"""
        expected = f"{API_BASE}/incidents/01ABC"
        self.assertEqual(api_url("/incidents/01ABC"), expected)


class MakeTimeoutTest(FakeAiohttpTestCase):
    """超时配置跟随实体常量。"""

    def test_total_matches_constant(self):
        """总超时等于实体常量里的 10 秒。"""
        install_fake_aiohttp()
        timeout = make_timeout()
        self.assertEqual(timeout.total, REQUEST_TIMEOUT_SECONDS)


class FetchSummaryTest(FakeAiohttpTestCase):
    """摘要请求：成功取 summary，失败按请求失败或结构异常分类。"""

    async def test_success_returns_summary(self):
        """200 且带 summary 时返回 summary，并按约定带请求头与超时。"""
        fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
        sessions = install_fake_aiohttp(response=FakeResponse(200, payload=fixture))
        summary = await fetch_summary()
        self.assertEqual(summary["ongoing_incidents"], fixture["summary"]["ongoing_incidents"])
        self.assertEqual(sessions[0].request_url, API_BASE)
        self.assertEqual(sessions[0].request_headers, {"Accept": "application/json"})
        # 替身会话默认没有超时对象；这里断言它确实被传入了
        assert sessions[0].timeout is not None
        self.assertEqual(sessions[0].timeout.total, REQUEST_TIMEOUT_SECONDS)

    async def test_non_200_includes_status_and_body(self):
        """非 200 抛 CollectorError，消息带状态码与响应体前 200 字。"""
        install_fake_aiohttp(response=FakeResponse(500, body="bad gateway"))
        with self.assertRaises(CollectorError) as caught:
            await fetch_summary()
        self.assertIn("HTTP 500", str(caught.exception))
        self.assertIn("bad gateway", str(caught.exception))

    async def test_non_200_body_is_truncated(self):
        """错误响应体只带前 200 字，避免整页 HTML 灌进日志。"""
        install_fake_aiohttp(response=FakeResponse(500, body="x" * 300))
        with self.assertRaises(CollectorError) as caught:
            await fetch_summary()
        self.assertEqual(str(caught.exception), "HTTP 500：" + "x" * 200)

    async def test_invalid_json_is_request_failure(self):
        """200 但正文不是合法 JSON：按请求失败抛 CollectorError。"""
        broken = FakeResponse(200, json_error=ValueError("Expecting value"))
        install_fake_aiohttp(response=broken)
        with self.assertRaises(CollectorError):
            await fetch_summary()

    async def test_missing_summary_is_structure_error(self):
        """200 但缺 summary 对象：抛 ValueError，让 monitor 记接口结构异常。"""
        install_fake_aiohttp(response=FakeResponse(200, payload={"data": {}}))
        with self.assertRaises(ValueError):
            await fetch_summary()

    async def test_connection_error_is_request_failure(self):
        """连不上目标站点：抛 CollectorError，不当成结构异常。"""
        install_fake_aiohttp(error=FakeClientError("connection refused"))
        with self.assertRaises(CollectorError) as caught:
            await fetch_summary()
        self.assertIn("请求失败", str(caught.exception))


# 允许直接 python3 tests/test_collector.py 运行本文件
if __name__ == "__main__":
    unittest.main()
