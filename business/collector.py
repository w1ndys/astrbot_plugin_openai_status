# 业务层采集：拼摘要接口地址、请求当前状态摘要。
# 本文件只依赖实体常量与 aiohttp，不读写数据库，也不解析业务规则。
from ..entity.constants import API_BASE, REQUEST_TIMEOUT_SECONDS

# 非 200 时只把响应体前这么多字符带进日志，避免网关整页 HTML 灌满日志
_ERROR_BODY_LIMIT = 200


class CollectorError(Exception):
    """请求层失败：连不上、超时、非 200 或响应不是合法 JSON；由 monitor 记「请求失败」。"""


def api_url(path: str) -> str:
    """拼出接口完整地址；path 为空就是摘要接口，否则必须自带前导斜杠。"""
    return API_BASE + path


def make_timeout():
    """构造 10 秒的总超时配置；aiohttp 延迟导入，未安装时也能导入本模块。"""
    import aiohttp

    return aiohttp.ClientTimeout(total=REQUEST_TIMEOUT_SECONDS)


async def fetch_summary() -> dict:
    """请求摘要接口并返回响应体里的 summary；请求失败抛 CollectorError，形状不符抛 ValueError。"""
    # aiohttp 延迟导入：AstrBot 运行时自带，纯函数测试不需要它
    import aiohttp

    try:
        async with aiohttp.ClientSession(timeout=make_timeout()) as session:
            async with session.get(
                api_url(""), headers={"Accept": "application/json"}
            ) as response:
                # 非 200 是接口拒绝或网关出错；带上响应体前 200 字，400 的错误码才进得了日志
                if response.status != 200:
                    body = await response.text()
                    raise CollectorError(f"HTTP {response.status}：{body[:_ERROR_BODY_LIMIT]}")
                # 只把 JSON 解析失败归到这一步，避免把读响应时的其它异常误判成正文问题
                try:
                    payload = await response.json()
                except ValueError as exc:
                    raise CollectorError(f"响应不是合法 JSON：{exc}") from exc
    except (aiohttp.ClientError, TimeoutError) as exc:
        # 连不上或超时：保留上一份快照，本轮不生成通知
        raise CollectorError(f"请求失败：{exc}") from exc

    # 200 却缺 summary 对象：接口形状变了，按结构异常处理，由 monitor 记「接口结构异常」
    if not isinstance(payload, dict) or not isinstance(payload.get("summary"), dict):
        raise ValueError("响应缺少 summary 对象")
    return payload["summary"]
