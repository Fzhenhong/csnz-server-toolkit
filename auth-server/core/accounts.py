"""账号注册 / 登录 / 封禁校验。

全部规则复刻自 CSNZ 服务端源码，任何偏差都会导致「登录器能登录但游戏进不去」：

1. RegisterUser（usermanager.cpp）的校验：
     密码 5-15 位，且不能是纯数字
     用户名 5-15 位，只能 字母+数字
2. Register（userdatabase_sqlite.cpp）只写 User 表，不建角色——这是刻意保持的。
   服务端 LoginUser 里有分支：
       if (!newUser->IsCharacterExists())  SendCharacter(socket);  // 弹建角
       else                                SendLoginPacket(...);    // 直接进大厅
   所以「注册只建账号、角色在游戏内创建」正是原生流程，符合预期。
   鉴权服务不去碰 UserCharacter 等表，避免与游戏端的建角逻辑打架。
3. userID 取自 UserDist.userIDNext 并自增，绝不能用 MAX(userID)+1，
   否则会与服务端游标冲突。
4. 密码是明文存储（VARCHAR(32)），服务端 SELECT ... WHERE password = ? 明文比对。
   鉴权服务因此也只能按明文校验——一旦改成哈希，游戏客户端自带的登录就失效。
5. 封禁有 3 种粒度：UserBan（账号）、IPBanList（IP）、HWIDBanList（硬件码）。
   登录放行必须三者都查。
"""
from __future__ import annotations

import re
import shutil
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

# 与服务端 definitions.h 一致
CSO_24_HOURS_IN_MINUTES = 1440

USERNAME_RE = re.compile(r"^[A-Za-z0-9]{5,15}$")


class AuthError(Exception):
    """带错误码的认证异常，码值与服务端 REGISTER_* / LOGIN_* 对齐。"""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def now_minutes() -> int:
    return int(datetime.now(timezone.utc).timestamp() // 60)


def validate_credentials(username: str, password: str) -> None:
    """严格复刻服务端 RegisterUser 的校验逻辑。"""
    if not (5 <= len(password) <= 15) or password.isdigit():
        raise AuthError(
            "PASSWORD_WRONG",
            "密码需 5-15 位，且不能是纯数字",
        )
    if not USERNAME_RE.match(username):
        raise AuthError(
            "USERNAME_WRONG",
            "账号需 5-15 位，只能包含英文字母和数字",
        )


class AccountStore:
    """直接操作 UserDatabase.db3。

    服务端用 PRAGMA foreign_keys = ON，这里同样开启，避免写出孤儿记录。
    """

    def __init__(self, db_path: Path, default_user: dict,
                 max_reg_per_ip: int = 3) -> None:
        self.db_path = db_path
        self.default_user = default_user or {}
        self.max_reg_per_ip = max_reg_per_ip

    # ---- 连接 ----
    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path), timeout=15)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    # ---- 查询 ----
    def get_user_id(self, username: str) -> int | None:
        with self._connect() as c:
            row = c.execute(
                "SELECT userID FROM User WHERE userName = ? LIMIT 1", (username,)
            ).fetchone()
            return int(row["userID"]) if row else None

    def get_account(self, user_id: int) -> dict | None:
        sql = """
        SELECT u.userID, u.userName, u.lastIP, u.lastHWID, u.registerTime,
               c.gameName, c.level, c.points
        FROM User u LEFT JOIN UserCharacter c ON c.userID = u.userID
        WHERE u.userID = ? LIMIT 1
        """
        with self._connect() as c:
            row = c.execute(sql, (user_id,)).fetchone()
            return dict(row) if row else None

    def is_banned(self, user_id: int) -> tuple[bool, str]:
        """账号封禁检查。term 是到期分钟戳，过期的服务端会自己删。"""
        with self._connect() as c:
            row = c.execute(
                "SELECT type, reason, term FROM UserBan WHERE userID = ? LIMIT 1",
                (user_id,),
            ).fetchone()
        if not row or not row["type"]:
            return False, ""
        if row["term"] and row["term"] <= now_minutes():
            return False, ""      # 已过期
        return True, row["reason"] or "账号已被封禁"

    def ban_ip(self, ip: str) -> None:
        """加入 IP 黑名单。服务端在 TCP 连接建立时即拒绝。"""
        with self._connect() as c:
            c.execute("INSERT OR IGNORE INTO IPBanList (ip) VALUES (?)", (ip,))
            c.commit()

    def is_ip_banned(self, ip: str) -> bool:
        with self._connect() as c:
            row = c.execute(
                "SELECT 1 FROM IPBanList WHERE ip = ? LIMIT 1", (ip,)
            ).fetchone()
            return row is not None

    def is_hwid_banned(self, hwid: bytes) -> bool:
        if not hwid:
            return False
        with self._connect() as c:
            row = c.execute(
                "SELECT 1 FROM HWIDBanList WHERE hwid = ? LIMIT 1", (hwid,)
            ).fetchone()
            return row is not None

    def verify_password(self, username: str, password: str) -> int:
        """明文比对，返回 userID。与服务端 SQL 完全一致。"""
        with self._connect() as c:
            row = c.execute(
                "SELECT userID FROM User WHERE userName = ? AND password = ? LIMIT 1",
                (username, password),
            ).fetchone()
        if not row:
            raise AuthError("LOGIN_FAILED", "账号或密码错误")
        return int(row["userID"])

    def is_online(self, user_id: int) -> bool:
        """UserSession 有行即在线：服务端登录时插入、登出时删除。"""
        with self._connect() as c:
            row = c.execute(
                "SELECT 1 FROM UserSession WHERE userID = ? LIMIT 1", (user_id,)
            ).fetchone()
            return row is not None

    def kick_session(self, user_id: int) -> bool:
        """清掉残留会话，让玩家能立即重新登录。

        注意：这只删数据库里的会话记录，服务端内存中的 IUser 对象仍在，
        必须配合管理工具踢人（或让服务端自动检测）才彻底生效。
        """
        with self._connect() as c:
            cur = c.execute("DELETE FROM UserSession WHERE userID = ?", (user_id,))
            c.commit()
            return cur.rowcount > 0

    # ---- 注册 ----
    def count_registrations_by_ip(self, ip: str) -> int:
        with self._connect() as c:
            row = c.execute(
                "SELECT COUNT(1) FROM User WHERE registerIP = ?", (ip,)
            ).fetchone()
            return int(row[0]) if row else 0

    def register(self, username: str, password: str, ip: str) -> int:
        """只注册账号（写 User 表），角色留给游戏内创建。

        返回新 userID。服务端在首次登录时发现无角色会自动弹建角界面。
        """
        validate_credentials(username, password)

        if self.is_ip_banned(ip):
            raise AuthError("IP_BANNED", "该 IP 已被封禁")
        if self.max_reg_per_ip and self.count_registrations_by_ip(ip) >= self.max_reg_per_ip:
            raise AuthError("REG_IP_LIMIT", f"该 IP 最多注册 {self.max_reg_per_ip} 个账号")

        conn = self._connect()
        try:
            exists = conn.execute(
                "SELECT 1 FROM User WHERE userName = ? LIMIT 1", (username,)
            ).fetchone()
            if exists:
                raise AuthError("USERNAME_EXIST", "该账号已存在")

            # userID 必须取自 UserDist 游标
            row = conn.execute("SELECT userIDNext FROM UserDist").fetchone()
            user_id = int(row[0]) if row else 1

            conn.execute(
                "INSERT INTO User (userID, userName, password, registerTime,"
                " registerIP, firstLogonTime, lastLogonTime, lastIP, lastHWID)"
                " VALUES (?, ?, ?, ?, ?, 0, 0, 0, x'')",
                (user_id, username, password, now_minutes(), ip),
            )
            conn.execute("UPDATE UserDist SET userIDNext = userIDNext + 1")

            conn.commit()
            return user_id
        except AuthError:
            conn.rollback()
            raise
        except Exception as e:
            conn.rollback()
            raise AuthError("DB_ERROR", f"数据库写入失败：{e}")
        finally:
            conn.close()

__all__ = ["AccountStore", "AuthError", "validate_credentials",
           "now_minutes", "CSO_24_HOURS_IN_MINUTES"]
