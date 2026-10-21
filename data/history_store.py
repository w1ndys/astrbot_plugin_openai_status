# 变更与推送记录：事件状态变化落库、推送结果与过期清理。
# 每条变化一行；推送记录保存正文与结果供排查，失败不重试。
import json
import sqlite3
from datetime import datetime, timedelta, timezone

from ..entity.models import StatusEvent
from .db import utc_now


def record_change(conn: sqlite3.Connection, event: StatusEvent, fetched_at: str) -> int:
    """为一条事件变化写一行变更记录，返回主键。"""
    # 组件名是列表，SQLite 没有数组类型，用 JSON 文本存；页面读出时再还原
    components = json.dumps(event.components, ensure_ascii=False)
    cursor = conn.execute(
        "INSERT INTO change_log"
        " (change_id, change_type, title, status, components, message, fetched_at)"
        " VALUES (?, ?, ?, ?, ?, ?, ?)",
        (
            event.change_id,
            event.change_type,
            event.title,
            event.status,
            components,
            event.message,
            fetched_at,
        ),
    )
    conn.commit()
    new_id = cursor.lastrowid
    # 插入后没有主键说明数据库异常，直接报错而不是返回半条记录
    if new_id is None:
        raise RuntimeError("变更记录插入后没有主键")
    return new_id


def list_changes(
    conn: sqlite3.Connection, page: int, size: int
) -> tuple[list[dict[str, object]], int]:
    """变更记录分页，按采集时间倒序；返回当页行与总数。"""
    total = conn.execute("SELECT COUNT(*) AS n FROM change_log").fetchone()["n"]
    # 页码与页大小做下限保护，避免负 OFFSET
    safe_page = max(page, 1)
    safe_size = max(size, 1)
    rows = conn.execute(
        "SELECT * FROM change_log ORDER BY fetched_at DESC, id DESC LIMIT ? OFFSET ?",
        (safe_size, (safe_page - 1) * safe_size),
    ).fetchall()
    result: list[dict[str, object]] = []
    for row in rows:
        # 直接转成字典，页面拿到 id / 事件字段 / 采集时间
        item = dict(row)
        # 组件名在库里是 JSON 文本；坏数据当成空列表，页面仍能显示这条记录
        try:
            parsed = json.loads(str(item.get("components") or "[]"))
        except json.JSONDecodeError:
            parsed = []
        item["components"] = parsed if isinstance(parsed, list) else []
        result.append(item)
    return result, int(total)


def record_push(
    conn: sqlite3.Connection,
    session: str,
    dedup_key: str,
    notify_type: str,
    message: str,
    ok: bool,
    error: str,
) -> None:
    """写一条推送结果；每次推送只写一条，不做覆盖更新。"""
    # 成功时 error 传空串；失败时保存原因与原始报错，方便事后排查
    conn.execute(
        "INSERT INTO push_records"
        " (session, dedup_key, notify_type, message, result, error, created_at)"
        " VALUES (?, ?, ?, ?, ?, ?, ?)",
        (session, dedup_key, notify_type, message, "ok" if ok else "failed", error, utc_now()),
    )
    conn.commit()


def purge_expired(conn: sqlite3.Connection, retention_days: int) -> int:
    """删除超过保留天数的变更记录与推送记录，返回删除总行数。"""
    # 保留天数小于 1 说明配置被手改坏；此时不动数据，避免把整库清空
    if retention_days < 1:
        return 0
    cutoff_time = datetime.now(timezone.utc) - timedelta(days=retention_days)
    # 与 utc_now() 同格式，固定长度 UTC 字符串按字典序比较就等于按时间比较
    cutoff = cutoff_time.strftime("%Y-%m-%dT%H:%M:%SZ")
    # 变更记录按采集时间判断；早于截止点才删，恰好等于截止点的记录保留
    changes = conn.execute("DELETE FROM change_log WHERE fetched_at < ?", (cutoff,))
    # 推送记录按推送完成时间判断；早于截止点才删，恰好等于截止点的记录保留
    pushes = conn.execute("DELETE FROM push_records WHERE created_at < ?", (cutoff,))
    conn.commit()
    return changes.rowcount + pushes.rowcount
