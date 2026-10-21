# 实体层固定值：接口地址、事件状态与中文映射、通知类型与展示时区。
# 本文件不依赖 AstrBot，也不访问数据库或网络。
from zoneinfo import ZoneInfo

# 插件名：AstrBot 用它定位插件目录，也是数据目录名的一部分
PLUGIN_NAME = "astrbot_plugin_openai_status"

# 状态页站点根地址，不带结尾斜杠；事件详情页与事件链接都用它
STATUS_PAGE_BASE = "https://status.openai.com"

# 摘要接口根地址：状态页自己的 Next.js 代理，页面重建时可能变
API_BASE = "https://status.openai.com/proxy/status.openai.com"

# 对外 HTTP 请求统一超时（秒）
REQUEST_TIMEOUT_SECONDS = 10

# 视为“已结束”的事件状态；这些状态不参与整体状态计算，也不因新出现而通知
CLOSED_EVENT_STATUSES = {"resolved", "maintenance_complete"}

# 只是排期、还没开始的维护；整体状态仍算正常，但出现时照常通知
UPCOMING_EVENT_STATUSES = {"maintenance_scheduled"}

# 整体状态：没有进行中的事件，也没有非正常组件
STATUS_NORMAL = "normal"

# 整体状态：至少一条进行中事件或一个非正常组件
STATUS_ABNORMAL = "abnormal"

# 事件状态中文映射：文案层查表显示；表里没有的状态值原样输出英文
STATUS_LABELS = {
    "investigating": "调查中",
    "identified": "已定位",
    "monitoring": "观察中",
    "resolved": "已解决",
    "maintenance_scheduled": "已排期",
    "maintenance_in_progress": "进行中",
    "maintenance_complete": "已完成",
}

# 事件类型中文映射：通知里标“故障”或“计划维护”；表里没有的类型原样输出
EVENT_TYPE_LABELS = {
    "incident": "故障",
    "maintenance": "计划维护",
}

# 通知类型：一轮事件状态变化的汇总通知
NOTIFY_CHANGES = "changes"

# 通知类型：开启订阅时主动查询得到的当前状态摘要
NOTIFY_SUMMARY = "summary"

# 默认指令名：注册时用；实际生效名由 AstrBot 指令管理决定
COMMAND_NAME = "oaistatus"

# 子命令：命令处理与帮助文案共用，改名只改这里
SUBCOMMAND_ON = "开"
SUBCOMMAND_OFF = "关"
SUBCOMMAND_HELP = "帮助"

# 默认展示时区：配置为空或非法时回退到这里；数据库里仍存 UTC
DEFAULT_TIMEZONE = ZoneInfo("Asia/Shanghai")
