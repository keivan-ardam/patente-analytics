"""SQLite persistence layer for analytics."""

import os
import sqlite3
import time
from contextlib import contextmanager
from typing import Optional

from .config import config

_SCHEMA = """
CREATE TABLE IF NOT EXISTS devices (
    device_id      TEXT PRIMARY KEY,
    first_seen     INTEGER NOT NULL,
    last_seen      INTEGER NOT NULL,
    session_count  INTEGER NOT NULL DEFAULT 0,
    country        TEXT
);

CREATE TABLE IF NOT EXISTS sessions (
    session_id   TEXT PRIMARY KEY,
    device_id    TEXT NOT NULL,
    started_at   INTEGER NOT NULL,
    last_seen    INTEGER NOT NULL,
    ended_at     INTEGER,
    user_agent   TEXT,
    country      TEXT
);

CREATE INDEX IF NOT EXISTS idx_sessions_last_seen ON sessions(last_seen);
CREATE INDEX IF NOT EXISTS idx_sessions_device ON sessions(device_id);
CREATE INDEX IF NOT EXISTS idx_sessions_started ON sessions(started_at);
"""


def init_db() -> None:
    """Create the database file and schema if they don't exist."""
    db_dir = os.path.dirname(config.DB_PATH)
    if db_dir:
        os.makedirs(db_dir, exist_ok=True)
    with _connect() as conn:
        conn.executescript(_SCHEMA)


@contextmanager
def _connect():
    conn = sqlite3.connect(config.DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def now() -> int:
    return int(time.time())


def upsert_device(device_id: str, ts: int, country: Optional[str], new_session: bool) -> bool:
    """Insert or update a device. Returns True if this is a brand-new device."""
    with _connect() as conn:
        row = conn.execute(
            "SELECT device_id FROM devices WHERE device_id = ?", (device_id,)
        ).fetchone()
        is_new = row is None
        if is_new:
            conn.execute(
                "INSERT INTO devices (device_id, first_seen, last_seen, session_count, country) "
                "VALUES (?, ?, ?, ?, ?)",
                (device_id, ts, ts, 1 if new_session else 0, country),
            )
        else:
            if new_session:
                conn.execute(
                    "UPDATE devices SET last_seen = ?, session_count = session_count + 1, "
                    "country = COALESCE(?, country) WHERE device_id = ?",
                    (ts, country, device_id),
                )
            else:
                conn.execute(
                    "UPDATE devices SET last_seen = ? WHERE device_id = ?",
                    (ts, device_id),
                )
        return is_new


def start_session(
    session_id: str,
    device_id: str,
    ts: int,
    user_agent: Optional[str],
    country: Optional[str],
) -> bool:
    """Create a session if it doesn't exist. Returns True if newly created."""
    with _connect() as conn:
        row = conn.execute(
            "SELECT session_id FROM sessions WHERE session_id = ?", (session_id,)
        ).fetchone()
        if row is not None:
            # Session already exists — treat as heartbeat
            conn.execute(
                "UPDATE sessions SET last_seen = ?, ended_at = NULL WHERE session_id = ?",
                (ts, session_id),
            )
            return False
        conn.execute(
            "INSERT INTO sessions (session_id, device_id, started_at, last_seen, ended_at, user_agent, country) "
            "VALUES (?, ?, ?, ?, NULL, ?, ?)",
            (session_id, device_id, ts, ts, user_agent, country),
        )
        return True


def touch_session(session_id: str, ts: int) -> None:
    """Update a session's last_seen (heartbeat)."""
    with _connect() as conn:
        conn.execute(
            "UPDATE sessions SET last_seen = ?, ended_at = NULL WHERE session_id = ?",
            (ts, session_id),
        )


def end_session(session_id: str, ts: int) -> None:
    """Mark a session as ended."""
    with _connect() as conn:
        conn.execute(
            "UPDATE sessions SET ended_at = ?, last_seen = ? WHERE session_id = ?",
            (ts, ts, session_id),
        )


def sweep_stale_sessions(timeout_seconds: int, ts: int) -> int:
    """Mark sessions with no recent heartbeat as ended. Returns count ended."""
    cutoff = ts - timeout_seconds
    with _connect() as conn:
        cur = conn.execute(
            "UPDATE sessions SET ended_at = ? WHERE ended_at IS NULL AND last_seen < ?",
            (ts, cutoff),
        )
        return cur.rowcount


def get_stats(active_window_seconds: int, ts: int) -> dict:
    """Aggregate current statistics."""
    active_cutoff = ts - active_window_seconds
    # Start of today (UTC midnight)
    today_start = ts - (ts % 86400)
    with _connect() as conn:
        active_sessions = conn.execute(
            "SELECT COUNT(*) AS c FROM sessions WHERE ended_at IS NULL AND last_seen >= ?",
            (active_cutoff,),
        ).fetchone()["c"]

        active_users = conn.execute(
            "SELECT COUNT(DISTINCT device_id) AS c FROM sessions "
            "WHERE ended_at IS NULL AND last_seen >= ?",
            (active_cutoff,),
        ).fetchone()["c"]

        total_devices = conn.execute(
            "SELECT COUNT(*) AS c FROM devices"
        ).fetchone()["c"]

        total_sessions = conn.execute(
            "SELECT COUNT(*) AS c FROM sessions"
        ).fetchone()["c"]

        sessions_today = conn.execute(
            "SELECT COUNT(*) AS c FROM sessions WHERE started_at >= ?",
            (today_start,),
        ).fetchone()["c"]

        devices_today = conn.execute(
            "SELECT COUNT(DISTINCT device_id) AS c FROM sessions WHERE started_at >= ?",
            (today_start,),
        ).fetchone()["c"]

    return {
        "active_users": active_users,
        "active_sessions": active_sessions,
        "total_devices": total_devices,
        "total_sessions": total_sessions,
        "sessions_today": sessions_today,
        "devices_today": devices_today,
    }
