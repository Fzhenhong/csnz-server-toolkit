"""鉴权事件记录。

单独存一个 SQLite 文件（auth_events.db3），**不写进 UserDatabase.db3**：
那个库的结构由服务端决定，多写表会带来升级风险；而事件只是运维数据。

GM 工具通过 /events 接口读这张表，实现「看到谁在撞库 → 一键封禁」。
只保留最近 N 天，写入时按概率触发清理，避免无限增长。
"""
from __future__ import annotations

import random
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS auth_event (
    id       INTEGER PRIMARY KEY AUTOINCREMENT,
    ts       INTEGER NOT NULL,
    kind     TEXT    NOT NULL,
    username TEXT,
    ip       TEXT,
    user_id  INTEGER,
    detail   TEXT
);
CREATE INDEX IF NOT EXISTS idx_event_ts ON auth_event(ts);
CREATE INDEX IF NOT EXISTS idx_event_kind ON auth_event(kind);
CREATE INDEX IF NOT EXISTS idx_event_ip ON auth_event(ip);
"""

# 事件类型
LOGIN_OK = "login_ok"
LOGIN_FAIL = "login_fail"
REGISTER_OK = "register_ok"
REGISTER_FAIL = "register_fail"
RATE_BLOCKED = "rate_blocked"
KICKED = "kicked"

KIND_LABELS = {
    LOGIN_OK: "登录成功",
    LOGIN_FAIL: "登录失败",
    REGISTER_OK: "注册成功",
    REGISTER_FAIL: "注册失败",
    RATE_BLOCKED: "触发限频",
    KICKED: "会话踢出",
}


def now_minutes() -> int:
    return int(datetime.now(timezone.utc).timestamp() // 60)


class EventStore:
    def __init__(self, path: Path, keep_days: int = 30) -> None:
        self.path = path
        self.keep_days = keep_days
        self._lock = threading.Lock()
        with self._conn() as c:
            c.executescript(SCHEMA)

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.path), timeout=10)
        conn.row_factory = sqlite3.Row
        return conn

    # ---- 写 ----
    def add(self, kind: str, username: str = "", ip: str = "",
            user_id: int = 0, detail: str = "") -> None:
        with self._lock:
            try:
                with self._conn() as c:
                    c.execute(
                        "INSERT INTO auth_event (ts, kind, username, ip, user_id, detail)"
                        " VALUES (?, ?, ?, ?, ?, ?)",
                        (now_minutes(), kind, username, ip, user_id or 0, detail),
                    )
                    # 小概率触发清理，避免每次写都扫表
                    if random.random() < 0.02:
                        cutoff = now_minutes() - self.keep_days * 1440
                        c.execute("DELETE FROM auth_event WHERE ts < ?", (cutoff,))
            except Exception:
                pass   # 事件记录失败不能影响登录

    # ---- 读 ----
    def recent(self, limit: int = 300, kind: str = "",
               ip: str = "", username: str = "") -> list[dict]:
        sql = "SELECT * FROM auth_event WHERE 1=1"
        args: list = []
        if kind:
            sql += " AND kind = ?"
            args.append(kind)
        if ip:
            sql += " AND ip LIKE ?"
            args.append(f"%{ip}%")
        if username:
            sql += " AND username LIKE ?"
            args.append(f"%{username}%")
        sql += " ORDER BY id DESC LIMIT ?"
        args.append(int(limit))
        with self._conn() as c:
            return [dict(r) for r in c.execute(sql, args)]

    def ip_summary(self, limit: int = 100) -> list[dict]:
        """按 IP 聚合失败次数，用于快速定位撞库来源。"""
        sql = """
        SELECT ip,
               COUNT(1) AS total,
               SUM(CASE WHEN kind = 'login_fail' THEN 1 ELSE 0 END) AS fails,
               SUM(CASE WHEN kind = 'login_ok' THEN 1 ELSE 0 END) AS oks,
               MAX(ts) AS last_ts
        FROM auth_event
        WHERE ip != ''
        GROUP BY ip
        ORDER BY fails DESC, total DESC
        LIMIT ?
        """
        with self._conn() as c:
            return [dict(r) for r in c.execute(sql, (int(limit),))]

    def stats(self) -> dict:
        with self._conn() as c:
            row = c.execute(
                "SELECT COUNT(1) AS total,"
                " SUM(CASE WHEN kind='login_ok' THEN 1 ELSE 0 END) AS ok,"
                " SUM(CASE WHEN kind='login_fail' THEN 1 ELSE 0 END) AS fail,"
                " SUM(CASE WHEN kind='rate_blocked' THEN 1 ELSE 0 END) AS blocked"
                " FROM auth_event"
            ).fetchone()
            return {
                "total": row["total"] or 0,
                "login_ok": row["ok"] or 0,
                "login_fail": row["fail"] or 0,
                "rate_blocked": row["blocked"] or 0,
            }


__all__ = ["EventStore", "KIND_LABELS", "LOGIN_OK", "LOGIN_FAIL",
           "REGISTER_OK", "REGISTER_FAIL", "RATE_BLOCKED", "KICKED"]
