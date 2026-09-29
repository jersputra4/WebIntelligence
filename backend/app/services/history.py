"""SQLite persistence for search history and account snapshots (MVP storage).

Snapshots of follower/following/post counts are recorded on each successful
lookup; the dashboard's trend chart is built from them, so it reflects only
data this installation has actually observed.
"""
from __future__ import annotations

import sqlite3
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.schemas.search import AccountResult

SCHEMA = """
CREATE TABLE IF NOT EXISTS search_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL,
    platform TEXT NOT NULL,
    searched_at TEXT NOT NULL,
    result_count INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL,
    status_code INTEGER NOT NULL,
    latency_ms INTEGER,
    error_code TEXT,
    display_name TEXT,
    avatar TEXT,
    verified INTEGER NOT NULL DEFAULT 0,
    result_platform TEXT
);
CREATE INDEX IF NOT EXISTS idx_history_searched_at ON search_history(searched_at);

CREATE TABLE IF NOT EXISTS account_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    platform TEXT NOT NULL,
    username TEXT NOT NULL,
    captured_at TEXT NOT NULL,
    display_name TEXT,
    followers INTEGER,
    following INTEGER,
    posts INTEGER,
    source TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_snapshots_account ON account_snapshots(platform, username, captured_at);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class HistoryRepository:
    def __init__(self, path: Path):
        self._path = path
        self._lock = threading.Lock()
        if str(path) != ":memory:":
            path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        with self._lock:
            self._conn.executescript(SCHEMA)
            self._conn.commit()

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    # ------------------------------------------------------------------ writes
    def record_search(self, *, username: str, platform: str, status: str, status_code: int,
                      results: list[AccountResult], latency_ms: int | None,
                      error_code: str | None = None) -> None:
        top = results[0] if results else None
        with self._lock:
            self._conn.execute(
                """INSERT INTO search_history (username, platform, searched_at, result_count, status,
                   status_code, latency_ms, error_code, display_name, avatar, verified, result_platform)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (username, platform, _now(), len(results), status, status_code, latency_ms, error_code,
                 top.display_name if top else None, top.avatar if top else None,
                 int(bool(top and top.verified)), top.platform if top else None),
            )
            for account in results:
                self._conn.execute(
                    """INSERT INTO account_snapshots (platform, username, captured_at, display_name,
                       followers, following, posts, source) VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                    (account.platform, account.username.lower(), _now(), account.display_name,
                     account.followers, account.following, account.posts, account.source),
                )
            self._conn.commit()

    def clear_history(self) -> int:
        with self._lock:
            cursor = self._conn.execute("DELETE FROM search_history")
            self._conn.commit()
            return cursor.rowcount

    # ------------------------------------------------------------------- reads
    def list_history(self, limit: int = 20, offset: int = 0) -> tuple[int, list[dict]]:
        with self._lock:
            total = self._conn.execute("SELECT COUNT(*) FROM search_history").fetchone()[0]
            rows = self._conn.execute(
                "SELECT * FROM search_history ORDER BY id DESC LIMIT ? OFFSET ?", (limit, offset)
            ).fetchall()
        items = []
        for row in rows:
            item = dict(row)
            item["verified"] = bool(item["verified"])
            items.append(item)
        return total, items

    def trend(self, platform: str, username: str, days: int = 30) -> list[dict]:
        since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat(timespec="seconds")
        with self._lock:
            rows = self._conn.execute(
                """SELECT captured_at, followers, following, posts FROM account_snapshots
                   WHERE platform = ? AND username = ? AND captured_at >= ?
                   ORDER BY captured_at ASC""",
                (platform, username.lower(), since),
            ).fetchall()
        return [dict(row) for row in rows]

    def daily_stats(self) -> dict:
        now = datetime.now(timezone.utc)
        today = now.strftime("%Y-%m-%d")
        yesterday = (now - timedelta(days=1)).strftime("%Y-%m-%d")
        with self._lock:
            today_row = self._conn.execute(
                """SELECT COUNT(*) AS n, AVG(CASE WHEN status = 'success' THEN latency_ms END) AS avg_ms,
                          SUM(CASE WHEN status = 'success' THEN 1 ELSE 0 END) AS ok
                   FROM search_history WHERE substr(searched_at, 1, 10) = ?""",
                (today,),
            ).fetchone()
            yesterday_count = self._conn.execute(
                "SELECT COUNT(*) FROM search_history WHERE substr(searched_at, 1, 10) = ?", (yesterday,)
            ).fetchone()[0]
            total = self._conn.execute("SELECT COUNT(*) FROM search_history").fetchone()[0]
        return {
            "today": today_row["n"] or 0,
            "today_success": today_row["ok"] or 0,
            "yesterday": yesterday_count,
            "avg_latency_ms": int(today_row["avg_ms"]) if today_row["avg_ms"] is not None else None,
            "total": total,
        }
