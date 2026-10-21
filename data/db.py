# 数据层连接与建表：打开 SQLite、设置 PRAGMA、建三张表与时间戳工具。
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from ..entity.constants import PLUGIN_NAME

# 建表语句：三张表与设计文档的列一一对应，重复执行不会报错
_SCHEMA = """
CREATE TABLE IF NOT EXISTS subscriptions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session TEXT NOT NULL UNIQUE,
    note TEXT NOT NULL DEFAULT '',
    enabled INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS change_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    change_id TEXT NOT NULL,
    change_type TEXT NOT NULL,
    title TEXT NOT NULL,
    status TEXT NOT NULL,
    components TEXT NOT NULL DEFAULT '[]',
    message TEXT NOT NULL DEFAULT '',
    fetched_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS push_records (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session TEXT NOT NULL,
    dedup_key TEXT NOT NULL,
    notify_type TEXT NOT NULL,
    message TEXT NOT NULL,
    result TEXT NOT NULL,
    error TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    UNIQUE(session, dedup_key)
);
"""


def connect(db_path: Path) -> sqlite3.Connection:
    """打开指定路径的 SQLite 连接，并设置行工厂与 WAL。"""
    conn = sqlite3.connect(str(db_path))
    # 按列名取值，store 里不用记列下标
    conn.row_factory = sqlite3.Row
    # WAL 让轮询写与页面读不互相堵
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    """建三张表并提交；表已存在时跳过。"""
    conn.executescript(_SCHEMA)
    conn.commit()


def utc_now() -> str:
    """当前 UTC 时间，ISO8601 带 Z；数据库所有时间列都用这个格式。"""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def get_db_path() -> Path:
    """返回插件数据目录下的数据库文件路径；只在插件运行时调用。"""
    # 延迟导入：测试环境不需要 astrbot，也避免顶层 import 影响纯函数
    from astrbot.core.star.star_tools import StarTools

    # 必须显式传插件名；从子模块调用不传名会抛 RuntimeError
    return Path(StarTools.get_data_dir(PLUGIN_NAME)) / "openai_status.db"
