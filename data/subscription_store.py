# 订阅表读写：列出订阅、按会话或主键查单条、命令开与关。
# 页面拿全部记录改开关；监控推送只要启用中的。
import sqlite3

from ..entity.models import Subscription
from .db import utc_now


def list_subscriptions(conn: sqlite3.Connection, only_enabled: bool = False) -> list[Subscription]:
    """列出订阅；only_enabled 为真时只返回启用中的，默认返回全部。"""
    if only_enabled:
        rows = conn.execute("SELECT * FROM subscriptions WHERE enabled = 1 ORDER BY id").fetchall()
    else:
        rows = conn.execute("SELECT * FROM subscriptions ORDER BY id").fetchall()
    result: list[Subscription] = []
    for row in rows:
        # 库里 enabled 是 0/1，还原成布尔值
        result.append(
            Subscription(
                id=row["id"],
                session=row["session"],
                note=row["note"],
                enabled=bool(row["enabled"]),
                created_at=row["created_at"],
                updated_at=row["updated_at"],
            )
        )
    return result


def get_by_session(conn: sqlite3.Connection, session: str) -> Subscription | None:
    """按会话标识查订阅；没有命中返回 None。"""
    row = conn.execute("SELECT * FROM subscriptions WHERE session = ?", (session,)).fetchone()
    # 没有这条会话就是没订阅，调用方按 None 分支处理
    if row is None:
        return None
    return Subscription(
        id=row["id"],
        session=row["session"],
        note=row["note"],
        enabled=bool(row["enabled"]),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def get_by_id(conn: sqlite3.Connection, sub_id: int) -> Subscription | None:
    """按主键查订阅；没有命中返回 None。"""
    row = conn.execute("SELECT * FROM subscriptions WHERE id = ?", (sub_id,)).fetchone()
    # 页面编辑前先确认记录还在，删过的 id 不能再用
    if row is None:
        return None
    return Subscription(
        id=row["id"],
        session=row["session"],
        note=row["note"],
        enabled=bool(row["enabled"]),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def enable_session(conn: sqlite3.Connection, session: str, note: str = "") -> tuple[Subscription, bool]:
    """命令「开」：新建订阅，或把已停用的订阅重新启用。"""
    existing = get_by_session(conn, session)
    # 已存在且启用：直接返回原记录，不覆盖备注
    if existing is not None and existing.enabled:
        return existing, False
    now = utc_now()
    # 新会话：插入一条启用中的订阅
    if existing is None:
        conn.execute(
            "INSERT INTO subscriptions (session, note, enabled, created_at, updated_at)"
            " VALUES (?, ?, 1, ?, ?)",
            (session, note, now, now),
        )
        conn.commit()
        created = get_by_session(conn, session)
        # 刚插入却查不到，说明数据库异常，直接报错
        if created is None:
            raise RuntimeError("订阅插入后查不到记录")
        return created, True
    # 已存在但停用：重新启用，备注保持原样
    conn.execute(
        "UPDATE subscriptions SET enabled = 1, updated_at = ? WHERE id = ?",
        (now, existing.id),
    )
    conn.commit()
    updated = get_by_id(conn, existing.id)
    if updated is None:
        raise RuntimeError("订阅启用后查不到记录")
    return updated, False


def disable_session(conn: sqlite3.Connection, session: str) -> bool:
    """命令「关」：把订阅置为停用；记录不存在时返回 False。"""
    cursor = conn.execute(
        "UPDATE subscriptions SET enabled = 0, updated_at = ? WHERE session = ?",
        (utc_now(), session),
    )
    conn.commit()
    # rowcount 为 0 说明这个会话根本没订阅过，命令层据此回复不同文案
    return cursor.rowcount > 0


def create(conn: sqlite3.Connection, session: str, note: str, enabled: bool) -> tuple[bool, str]:
    """页面新增订阅；会话标识为空或重复时返回失败原因。"""
    # 空会话标识无法定位推送目标，页面必须拦下
    if not session.strip():
        return False, "会话标识不能为空"
    # 会话标识唯一，重复时保留原有记录
    if get_by_session(conn, session) is not None:
        return False, "会话标识已存在"
    now = utc_now()
    conn.execute(
        "INSERT INTO subscriptions (session, note, enabled, created_at, updated_at)"
        " VALUES (?, ?, ?, ?, ?)",
        (session, note, 1 if enabled else 0, now, now),
    )
    conn.commit()
    return True, ""


def update(
    conn: sqlite3.Connection, sub_id: int, session: str, note: str, enabled: bool
) -> bool:
    """页面编辑订阅；主键不存在时返回 False。"""
    cursor = conn.execute(
        "UPDATE subscriptions SET session = ?, note = ?, enabled = ?, updated_at = ?"
        " WHERE id = ?",
        (session, note, 1 if enabled else 0, utc_now(), sub_id),
    )
    conn.commit()
    # rowcount 为 0 说明记录已被别处删掉，页面应刷新列表
    return cursor.rowcount > 0


def delete(conn: sqlite3.Connection, sub_id: int) -> bool:
    """页面删除订阅；主键不存在时返回 False。"""
    cursor = conn.execute("DELETE FROM subscriptions WHERE id = ?", (sub_id,))
    conn.commit()
    # 没删到行说明这条订阅已经不存在，页面按失败提示并刷新
    return cursor.rowcount > 0
