# 类型桩：本机没有安装 AstrBot，用最小声明让 pyrefly 解析插件依赖。
# 只声明已用到的接口；新增调用时按 AstrBot 源码补签名。
from pathlib import Path


class StarTools:
    """AstrBot 的插件工具集；这里只声明数据目录入口。"""

    # 返回 data/plugin_data/{plugin_name} 的绝对路径，并确保目录已创建
    @classmethod
    def get_data_dir(cls, plugin_name: str | None = None) -> Path: ...
