# 测试包。把仓库上一级插进 sys.path，测试就能按包名导入 astrbot_plugin_deepseek_status。
import sys
from pathlib import Path

PARENT = str(Path(__file__).resolve().parents[2])
# 重复插入会让后导入的测试拿到错误的包，所以先查一遍
if PARENT not in sys.path:
    sys.path.insert(0, PARENT)
