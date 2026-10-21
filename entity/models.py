# 实体层数据形状：状态事件、快照、订阅与待推送通知。
# 只放字段定义，不做校验也不读写；字段默认值由调用方显式传入。
from dataclasses import dataclass


@dataclass
class StatusEvent:
    """状态页上的一条事件，含已结束的；由解析层产出，供整体状态计算与变化比对。"""

    # 事件 ID（ULID 字符串），也是详情页路径参数
    change_id: str
    # 事件类型：incident 或 maintenance
    change_type: str
    # 事件标题
    title: str
    # 事件状态，例如 investigating、maintenance_in_progress
    status: str
    # 事件详情页链接
    link: str
    # 受影响组件名称；接口只给 ID，解析层已经换成名字
    components: list[str]
    # 最新一条更新的正文；没有更新时为空串
    message: str


@dataclass
class Snapshot:
    """最近一次成功采集得到的整体状态快照。"""

    # 整体状态：normal 或 abnormal，按进行中事件与非正常组件计算
    status: str
    # 进行中事件与计划维护列表（含已结束条目）；变化比对用它
    events: list[StatusEvent]
    # 采集时间，UTC ISO8601 带 Z
    fetched_at: str


@dataclass
class Subscription:
    """一条推送订阅。"""

    # 数据库主键
    id: int
    # 会话标识，AstrBot 的 unified_msg_origin
    session: str
    # 备注名，供页面辨认
    note: str
    # 是否启用；停用后不推送
    enabled: bool
    # 创建时间，UTC ISO8601 带 Z
    created_at: str
    # 最后更新时间，UTC ISO8601 带 Z
    updated_at: str


@dataclass
class Notification:
    """一条待推送通知，消息正文已渲染好。"""

    # 通知类型：changes（一轮变化汇总）或 summary（订阅时的当前状态）
    notify_type: str
    # 去重键，同会话同键只推一次
    dedup_key: str
    # 已渲染好的消息文本
    message: str


@dataclass
class MonitorConfig:
    """监控运行需要的配置，由入口层从原始 dict 转换后注入。"""

    # 监控总开关
    enabled: bool
    # 轮询间隔（秒）
    poll_interval_seconds: int
    # 是否推送通知
    notify_enabled: bool
    # 变更记录与推送记录的保留天数
    history_retention_days: int
    # 展示时区的 IANA 名称，未解析成 ZoneInfo
    display_timezone: str
