"""QR Short Bot — SQLite with My QR, expiry, revoke, edit."""
from __future__ import annotations

import secrets
import sqlite3
import threading
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from config import DB_PATH

_LOCK = threading.RLock()


def get_conn() -> sqlite3.Connection:
    with _LOCK:
        c = sqlite3.connect(DB_PATH, timeout=30)
        c.row_factory = sqlite3.Row
        c.execute("PRAGMA journal_mode=WAL")
        return c


def init_db():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    c = get_conn()
    c.executescript(
        """
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            full_name TEXT,
            name TEXT,
            registered_at TEXT DEFAULT (datetime('now')),
            last_active TEXT,
            qr_count INTEGER DEFAULT 0,
            short_count INTEGER DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS qr_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            code TEXT UNIQUE,
            user_id INTEGER NOT NULL,
            title TEXT,
            content TEXT NOT NULL,
            kind TEXT DEFAULT 'text',
            status TEXT DEFAULT 'active',
            expires_at TEXT,
            created_at TEXT DEFAULT (datetime('now')),
            updated_at TEXT DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS short_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            code TEXT UNIQUE,
            user_id INTEGER NOT NULL,
            original TEXT NOT NULL,
            shortened TEXT NOT NULL,
            status TEXT DEFAULT 'active',
            expires_at TEXT,
            created_at TEXT DEFAULT (datetime('now')),
            updated_at TEXT DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS qr_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            content TEXT,
            file_size INTEGER,
            created_at TEXT DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS short_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            original TEXT,
            shortened TEXT,
            created_at TEXT DEFAULT (datetime('now'))
        );
        CREATE INDEX IF NOT EXISTS idx_qr_user ON qr_items(user_id);
        CREATE INDEX IF NOT EXISTS idx_short_user ON short_items(user_id);
        """
    )
    c.commit()
    c.close()


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: Optional[datetime]) -> Optional[str]:
    return dt.isoformat() if dt else None


def _parse_iso(s: Optional[str]) -> Optional[datetime]:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s)
    except Exception:
        return None


def _code(n: int = 8) -> str:
    return secrets.token_urlsafe(n)[:n]


def upsert_user(user_id: int, username: str, full_name: str):
    c = get_conn()
    now = _now().isoformat()
    c.execute(
        """
        INSERT INTO users (user_id, username, full_name, last_active)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(user_id) DO UPDATE SET
            username=excluded.username,
            full_name=excluded.full_name,
            last_active=excluded.last_active
        """,
        (user_id, username, full_name, now),
    )
    c.commit()
    return get_user(user_id)


def get_user(user_id: int) -> Optional[dict]:
    c = get_conn()
    r = c.execute("SELECT * FROM users WHERE user_id=?", (user_id,)).fetchone()
    c.close()
    return dict(r) if r else None


def set_user_name(user_id: int, name: str):
    c = get_conn()
    c.execute("UPDATE users SET name=? WHERE user_id=?", (name, user_id))
    c.commit()
    c.close()


def bump_qr(user_id: int, content: str, size: int):
    c = get_conn()
    c.execute("UPDATE users SET qr_count = qr_count + 1 WHERE user_id=?", (user_id,))
    c.execute(
        "INSERT INTO qr_logs (user_id, content, file_size) VALUES (?,?,?)",
        (user_id, content, size),
    )
    c.commit()
    c.close()


def bump_short(user_id: int, original: str, shortened: str):
    c = get_conn()
    c.execute("UPDATE users SET short_count = short_count + 1 WHERE user_id=?", (user_id,))
    c.execute(
        "INSERT INTO short_logs (user_id, original, shortened) VALUES (?,?,?)",
        (user_id, original, shortened),
    )
    c.commit()
    c.close()


def all_users() -> List[dict]:
    c = get_conn()
    rows = c.execute(
        "SELECT user_id, username, full_name, name, qr_count, short_count, registered_at "
        "FROM users ORDER BY registered_at DESC"
    ).fetchall()
    c.close()
    return [dict(r) for r in rows]


def stats() -> dict:
    c = get_conn()
    n_users = c.execute("SELECT COUNT(*) FROM users").fetchone()[0]
    n_qr = c.execute("SELECT COUNT(*) FROM qr_items WHERE status='active'").fetchone()[0]
    n_short = c.execute("SELECT COUNT(*) FROM short_items WHERE status='active'").fetchone()[0]
    n_qr_log = c.execute("SELECT COUNT(*) FROM qr_logs").fetchone()[0]
    n_short_log = c.execute("SELECT COUNT(*) FROM short_logs").fetchone()[0]
    c.close()
    return {
        "users": n_users,
        "qr": n_qr_log,
        "short": n_short_log,
        "qr_active": n_qr,
        "short_active": n_short,
    }


def create_qr_item(
    user_id: int,
    content: str,
    kind: str = "text",
    title: str = "",
    expires_hours: Optional[int] = None,
) -> dict:
    c = get_conn()
    code = _code(8)
    exp = _now() + timedelta(hours=expires_hours) if expires_hours else None
    now = _now().isoformat()
    c.execute(
        """
        INSERT INTO qr_items (code, user_id, title, content, kind, status, expires_at, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, 'active', ?, ?, ?)
        """,
        (code, user_id, title or kind, content, kind, _iso(exp), now, now),
    )
    c.commit()
    row = c.execute("SELECT * FROM qr_items WHERE code=?", (code,)).fetchone()
    c.close()
    return dict(row)


def create_short_item(
    user_id: int,
    original: str,
    shortened: str,
    expires_hours: Optional[int] = None,
) -> dict:
    c = get_conn()
    code = _code(8)
    exp = _now() + timedelta(hours=expires_hours) if expires_hours else None
    now = _now().isoformat()
    c.execute(
        """
        INSERT INTO short_items (code, user_id, original, shortened, status, expires_at, created_at, updated_at)
        VALUES (?, ?, ?, ?, 'active', ?, ?, ?)
        """,
        (code, user_id, original, shortened, _iso(exp), now, now),
    )
    c.commit()
    row = c.execute("SELECT * FROM short_items WHERE code=?", (code,)).fetchone()
    c.close()
    return dict(row)


def _refresh_expiry(table: str):
    """Mark expired rows."""
    c = get_conn()
    now = _now().isoformat()
    c.execute(
        f"UPDATE {table} SET status='expired' WHERE status='active' AND expires_at IS NOT NULL AND expires_at < ?",
        (now,),
    )
    c.commit()
    c.close()


def list_qr_items(user_id: int, limit: int = 20) -> List[dict]:
    _refresh_expiry("qr_items")
    c = get_conn()
    rows = c.execute(
        """
        SELECT * FROM qr_items
        WHERE user_id=? AND status!='deleted'
        ORDER BY id DESC LIMIT ?
        """,
        (user_id, limit),
    ).fetchall()
    c.close()
    return [dict(r) for r in rows]


def list_short_items(user_id: int, limit: int = 20) -> List[dict]:
    _refresh_expiry("short_items")
    c = get_conn()
    rows = c.execute(
        """
        SELECT * FROM short_items
        WHERE user_id=? AND status!='deleted'
        ORDER BY id DESC LIMIT ?
        """,
        (user_id, limit),
    ).fetchall()
    c.close()
    return [dict(r) for r in rows]


def get_qr_item(code: str, user_id: Optional[int] = None) -> Optional[dict]:
    _refresh_expiry("qr_items")
    c = get_conn()
    if user_id is None:
        r = c.execute("SELECT * FROM qr_items WHERE code=?", (code,)).fetchone()
    else:
        r = c.execute(
            "SELECT * FROM qr_items WHERE code=? AND user_id=?", (code, user_id)
        ).fetchone()
    c.close()
    return dict(r) if r else None


def get_short_item(code: str, user_id: Optional[int] = None) -> Optional[dict]:
    _refresh_expiry("short_items")
    c = get_conn()
    if user_id is None:
        r = c.execute("SELECT * FROM short_items WHERE code=?", (code,)).fetchone()
    else:
        r = c.execute(
            "SELECT * FROM short_items WHERE code=? AND user_id=?", (code, user_id)
        ).fetchone()
    c.close()
    return dict(r) if r else None


def edit_qr_item(code: str, user_id: int, content: str, title: Optional[str] = None) -> Optional[dict]:
    c = get_conn()
    now = _now().isoformat()
    if title is None:
        c.execute(
            "UPDATE qr_items SET content=?, updated_at=?, status='active' WHERE code=? AND user_id=? AND status!='deleted'",
            (content, now, code, user_id),
        )
    else:
        c.execute(
            "UPDATE qr_items SET content=?, title=?, updated_at=?, status='active' WHERE code=? AND user_id=? AND status!='deleted'",
            (content, title, now, code, user_id),
        )
    c.commit()
    row = c.execute(
        "SELECT * FROM qr_items WHERE code=? AND user_id=?", (code, user_id)
    ).fetchone()
    c.close()
    return dict(row) if row else None


def revoke_qr_item(code: str, user_id: int) -> bool:
    c = get_conn()
    now = _now().isoformat()
    cur = c.execute(
        "UPDATE qr_items SET status='revoked', updated_at=? WHERE code=? AND user_id=? AND status='active'",
        (now, code, user_id),
    )
    c.commit()
    ok = cur.rowcount > 0
    c.close()
    return ok


def revoke_short_item(code: str, user_id: int) -> bool:
    c = get_conn()
    now = _now().isoformat()
    cur = c.execute(
        "UPDATE short_items SET status='revoked', updated_at=? WHERE code=? AND user_id=? AND status='active'",
        (now, code, user_id),
    )
    c.commit()
    ok = cur.rowcount > 0
    c.close()
    return ok


def set_qr_expiry(code: str, user_id: int, hours: Optional[int]) -> Optional[dict]:
    c = get_conn()
    now = _now()
    exp = now + timedelta(hours=hours) if hours else None
    c.execute(
        "UPDATE qr_items SET expires_at=?, updated_at=?, status='active' WHERE code=? AND user_id=? AND status!='deleted'",
        (_iso(exp), now.isoformat(), code, user_id),
    )
    c.commit()
    row = c.execute(
        "SELECT * FROM qr_items WHERE code=? AND user_id=?", (code, user_id)
    ).fetchone()
    c.close()
    return dict(row) if row else None


def set_short_expiry(code: str, user_id: int, hours: Optional[int]) -> Optional[dict]:
    c = get_conn()
    now = _now()
    exp = now + timedelta(hours=hours) if hours else None
    c.execute(
        "UPDATE short_items SET expires_at=?, updated_at=?, status='active' WHERE code=? AND user_id=? AND status!='deleted'",
        (_iso(exp), now.isoformat(), code, user_id),
    )
    c.commit()
    row = c.execute(
        "SELECT * FROM short_items WHERE code=? AND user_id=?", (code, user_id)
    ).fetchone()
    c.close()
    return dict(row) if row else None


def item_status_label(item: dict) -> str:
    st = item.get("status") or "active"
    if st == "revoked":
        return "🚫 revoked"
    if st == "expired":
        return "⌛ expired"
    exp = _parse_iso(item.get("expires_at"))
    if exp and exp < _now():
        return "⌛ expired"
    if exp:
        return f"✅ active · exp {exp.strftime('%Y-%m-%d %H:%M')} UTC"
    return "✅ active · no expiry"
