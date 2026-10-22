"""UserDatabase.db3 读写层。

写入规则全部复刻自服务端源码（CItemManager::AddItem、CUserDatabaseSQLite::AddInventoryItem），
违反这些规则会造成背包错乱或数据被服务端覆盖：

1. 时间戳单位是「分钟」（GetCurrentTime 返回 m_CurrentTime，注释即 timestamp in minutes）。
2. 新道具优先复用 itemID=0 的空槽行；没有空槽才用 nextInventorySlot 插入并自增。
3. 可堆叠道具（Category 9 且 UseType∈{0,1,2}，或 Category 8 且 UseType∈{0,2}）同 ID 累加 count，不新建行。
4. 永久道具 status=1、inUse=1、expiryDate=0；限时道具 expiryDate=now+duration*1440。
5. 同 ID 已永久持有又要发限时的，走延长 expiryDate，而不是新增行。
6. itemID=166（密码箱）不占槽位，累加 UserCharacter.passwordBoxes。
7. 装扮（Category 12 / ClassName==Tattoo）入库只是持有，穿上要另写 UserCostumeLoadout。
8. 有效道具数 >= ServerConfig.InventorySlotMax 视为背包满。
"""
from __future__ import annotations

import shutil
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path

from .itemdb import Item, is_stackable

CSO_24_HOURS_IN_MINUTES = 1440
PASSWORD_BOX_ITEM = 166


def now_minutes() -> int:
    """服务端时间轴：Unix 秒 / 60。"""
    return int(time.time() // 60)


def minutes_to_str(m: int, permanent_label: str = "永久") -> str:
    if not m:
        return permanent_label
    ts = datetime.fromtimestamp(m * 60, tz=timezone.utc).astimezone()
    return ts.strftime("%Y-%m-%d %H:%M")


def days_left(expiry_min: int) -> str:
    if not expiry_min:
        return "永久"
    delta = expiry_min - now_minutes()
    if delta <= 0:
        return "已过期"
    return f"{delta / CSO_24_HOURS_IN_MINUTES:.1f} 天"


class InventoryRow:
    __slots__ = ("slot", "item_id", "count", "status", "in_use",
                 "obtain", "expiry", "clan", "lock", "paint", "enh")

    def __init__(self, r: sqlite3.Row) -> None:
        self.slot = r["slot"]
        self.item_id = r["itemID"]
        self.count = r["count"]
        self.status = r["status"]
        self.in_use = r["inUse"]
        self.obtain = r["obtainDate"]
        self.expiry = r["expiryDate"]
        self.clan = r["isClanItem"]
        self.lock = r["lockStatus"]
        self.paint = r["paintID"]
        self.enh = r["enhancementLevel"]


class User:
    __slots__ = ("user_id", "username", "game_name", "level", "points", "cash",
                 "exp", "battles", "kills", "deaths", "honor", "mileage",
                 "clan_id", "gm", "online", "last_ip", "last_login", "register",
                 "slot_max", "next_slot", "banned", "ban_reason", "ban_type",
                 "ban_term", "item_count")

    def __init__(self) -> None:
        self.user_id = 0
        self.username = ""
        self.game_name = ""
        self.level = 0
        self.points = 0
        self.cash = 0
        self.exp = 0
        self.battles = 0
        self.kills = 0
        self.deaths = 0
        self.honor = 0
        self.mileage = 0
        self.clan_id = 0
        self.gm = 0
        self.online = False
        self.last_ip = ""
        self.last_login = 0
        self.register = 0
        self.slot_max = 4000
        self.next_slot = 0
        self.banned = 0
        self.ban_reason = ""
        self.ban_type = 0
        self.ban_term = 0
        self.item_count = 0


class Database:
    """一次连接服务所有界面；写操作走事务并自动备份。"""

    def __init__(self, db_path: Path) -> None:
        self.path = db_path
        self.conn: sqlite3.Connection | None = None
        self.slot_max_default = 4000

    # ---- 连接 ----
    def connect(self) -> None:
        self.close()
        self.conn = sqlite3.connect(str(self.path), timeout=10)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")

    def close(self) -> None:
        if self.conn:
            self.conn.close()
            self.conn = None

    def _c(self) -> sqlite3.Connection:
        if not self.conn:
            self.connect()
        assert self.conn is not None
        return self.conn

    def backup(self, backup_dir: Path, max_keep: int = 50) -> Path:
        backup_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        dst = backup_dir / f"UserDatabase_{stamp}.db3"
        self._c().commit()
        shutil.copy2(self.path, dst)
        olds = sorted(backup_dir.glob("UserDatabase_*.db3"))
        for old in olds[:-max_keep] if len(olds) > max_keep else []:
            try:
                old.unlink()
            except OSError:
                pass
        return dst

    # ---- 读取 ----
    def schema_version(self) -> int:
        row = self._c().execute("PRAGMA user_version").fetchone()
        return int(row[0]) if row else 0

    def inventory_slot_max(self, server_config_slot_max: int) -> int:
        return server_config_slot_max or self.slot_max_default

    def list_users(self) -> list[User]:
        sql = """
        SELECT u.userID, u.userName, u.lastIP, u.lastLogonTime, u.registerTime,
               c.gameName, c.level, c.points, c.cash, c.exp, c.battles,
               c.kills, c.deaths, c.honorPoints, c.mileagePoints, c.clanID,
               COALESCE(e.gameMaster, 0) AS gm,
               COALESCE(e.nextInventorySlot, 0) AS nextSlot,
               (SELECT COUNT(1) FROM UserSession s WHERE s.userID = u.userID) AS online,
               COALESCE(b.type, 0) AS banType,
               COALESCE(b.reason, '') AS banReason,
               COALESCE(b.term, 0) AS banTerm,
               (SELECT COUNT(1) FROM UserInventory i
                 WHERE i.userID = u.userID AND i.itemID != 0) AS itemCount
        FROM User u
        LEFT JOIN UserCharacter c ON c.userID = u.userID
        LEFT JOIN UserCharacterExtended e ON e.userID = u.userID
        LEFT JOIN UserBan b ON b.userID = u.userID
        ORDER BY u.userID
        """
        out: list[User] = []
        for r in self._c().execute(sql):
            u = User()
            u.user_id = r["userID"]
            u.username = r["userName"] or ""
            u.game_name = r["gameName"] or ""
            u.level = r["level"] or 0
            u.points = r["points"] or 0
            u.cash = r["cash"] or 0
            u.exp = r["exp"] or 0
            u.battles = r["battles"] or 0
            u.kills = r["kills"] or 0
            u.deaths = r["deaths"] or 0
            u.honor = r["honorPoints"] or 0
            u.mileage = r["mileagePoints"] or 0
            u.clan_id = r["clanID"] or 0
            u.gm = r["gm"] or 0
            u.next_slot = r["nextSlot"] or 0
            u.online = bool(r["online"])
            u.last_ip = r["lastIP"] or ""
            u.last_login = r["lastLogonTime"] or 0
            u.register = r["registerTime"] or 0
            u.ban_type = r["banType"] or 0
            u.ban_reason = r["banReason"] or ""
            u.ban_term = r["banTerm"] or 0
            # term 是到期分钟戳：已过期的不算封禁中。
            # 服务端每分钟会 DELETE FROM UserBan WHERE term <= now，
            # 但如果服务端没在跑，过期行会残留在库里，直接按 ban_type 判断会误报。
            u.banned = 1 if (u.ban_type and self._ban_active(u.ban_term)) else 0
            u.item_count = r["itemCount"] or 0
            out.append(u)
        return out

    @staticmethod
    def _ban_active(term: int) -> bool:
        """term=0 视为永久封禁；否则比较到期分钟戳。"""
        if not term:
            return True
        return term > now_minutes()

    def get_user(self, user_id: int) -> User | None:
        for u in self.list_users():
            if u.user_id == user_id:
                return u
        return None

    def find_user_by_name(self, name: str) -> User | None:
        name = name.strip()
        if not name:
            return None
        if name.isdigit():
            return self.get_user(int(name))
        sql = """
        SELECT u.userID FROM User u
        LEFT JOIN UserCharacter c ON c.userID = u.userID
        WHERE u.userName = ? OR c.gameName = ?
        LIMIT 1
        """
        row = self._c().execute(sql, (name, name)).fetchone()
        return self.get_user(int(row[0])) if row else None

    def inventory(self, user_id: int) -> list[InventoryRow]:
        sql = "SELECT * FROM UserInventory WHERE userID = ? ORDER BY slot"
        return [InventoryRow(r) for r in self._c().execute(sql, (user_id,))]

    def inventory_count(self, user_id: int) -> int:
        row = self._c().execute(
            "SELECT COUNT(1) FROM UserInventory WHERE userID = ? AND itemID != 0",
            (user_id,),
        ).fetchone()
        return int(row[0]) if row else 0

    def owned_item_ids(self, user_id: int) -> set[int]:
        rows = self._c().execute(
            "SELECT DISTINCT itemID FROM UserInventory WHERE userID = ? AND itemID != 0",
            (user_id,),
        )
        return {int(r[0]) for r in rows}

    # ---- 在线状态 ----
    def online_count(self) -> int:
        """在线人数以 UserSession 为准。

        服务端在 Login 成功后 INSERT UserSession，登出（DropSession）时删除，
        所以该表行数就是当前真正已登录的会话数，比 User.lastLogonTime 可靠。
        """
        row = self._c().execute("SELECT COUNT(1) FROM UserSession").fetchone()
        return int(row[0]) if row else 0

    def online_users(self) -> list[tuple[int, str, str, str, int]]:
        """返回 (userID, 账号, 昵称, IP, 已在线秒数)。"""
        sql = """
        SELECT s.userID, u.userName, COALESCE(c.gameName,'') AS gameName,
               s.ip, COALESCE(s.sessionTime, 0) AS sessionTime
        FROM UserSession s
        LEFT JOIN User u ON u.userID = s.userID
        LEFT JOIN UserCharacter c ON c.userID = s.userID
        ORDER BY s.userID
        """
        out = []
        for r in self._c().execute(sql):
            out.append((
                int(r["userID"]), r["userName"] or "", r["gameName"] or "",
                r["ip"] or "", int(r["sessionTime"] or 0) * 60,
            ))
        return out

    def ban_lists(self) -> tuple[list[str], list[bytes]]:
        ips = [r[0] for r in self._c().execute("SELECT ip FROM IPBanList")]
        hwids = [bytes(r[0]) for r in self._c().execute("SELECT hwid FROM HWIDBanList")]
        return ips, hwids

    def recent_sessions(self, limit: int = 200) -> list[sqlite3.Row]:
        sql = """
        SELECT h.userID, u.userName, h.ip, h.sessionDate, h.sessionTime
        FROM UserSessionHistory h LEFT JOIN User u ON u.userID = h.userID
        ORDER BY h.sessionDate DESC LIMIT ?
        """
        return list(self._c().execute(sql, (limit,)))

    # ---- 写入：角色数值 ----
    def set_character_fields(self, user_id: int, **fields) -> None:
        allowed = {"points", "cash", "exp", "level", "honorPoints", "mileagePoints",
                   "battles", "kills", "deaths", "passwordBoxes", "gameName"}
        sets = {k: v for k, v in fields.items() if k in allowed}
        if not sets:
            return
        cols = ", ".join(f"{k} = ?" for k in sets)
        self._c().execute(
            f"UPDATE UserCharacter SET {cols} WHERE userID = ?",
            (*sets.values(), user_id),
        )
        self._c().commit()

    def adjust_points(self, user_id: int, delta: int) -> int:
        self._c().execute(
            "UPDATE UserCharacter SET points = MAX(0, points + ?) WHERE userID = ?",
            (delta, user_id),
        )
        self._c().commit()
        row = self._c().execute(
            "SELECT points FROM UserCharacter WHERE userID = ?", (user_id,)
        ).fetchone()
        return int(row[0]) if row else 0

    def set_gamemaster(self, user_id: int, enabled: bool) -> None:
        self._c().execute(
            "UPDATE UserCharacterExtended SET gameMaster = ? WHERE userID = ?",
            (1 if enabled else 0, user_id),
        )
        self._c().commit()

    # ---- 写入：封禁 ----
    def ban_user(self, user_id: int, ban_type: int, reason: str, days: int) -> None:
        """ban_type: 1=显示理由 2=静默；0 视为解封。term 为到期分钟时间戳。"""
        c = self._c()
        if ban_type == 0 or days <= 0:
            c.execute("DELETE FROM UserBan WHERE userID = ?", (user_id,))
        else:
            term = now_minutes() + days * CSO_24_HOURS_IN_MINUTES
            exists = c.execute(
                "SELECT 1 FROM UserBan WHERE userID = ?", (user_id,)
            ).fetchone()
            if exists:
                c.execute(
                    "UPDATE UserBan SET type = ?, reason = ?, term = ? WHERE userID = ?",
                    (ban_type, reason, term, user_id),
                )
            else:
                c.execute(
                    "INSERT INTO UserBan (userID, type, reason, term) VALUES (?, ?, ?, ?)",
                    (user_id, ban_type, reason, term),
                )
        c.commit()

    def ban_ip(self, ip: str) -> None:
        c = self._c()
        c.execute("INSERT OR IGNORE INTO IPBanList (ip) VALUES (?)", (ip,))
        c.commit()

    def unban_ip(self, ip: str) -> None:
        c = self._c()
        c.execute("DELETE FROM IPBanList WHERE ip = ?", (ip,))
        c.commit()

    def ban_hwid(self, hwid: bytes) -> None:
        c = self._c()
        c.execute("INSERT OR IGNORE INTO HWIDBanList (hwid) VALUES (?)", (hwid,))
        c.commit()

    def unban_hwid(self, hwid: bytes) -> None:
        c = self._c()
        c.execute("DELETE FROM HWIDBanList WHERE hwid = ?", (hwid,))
        c.commit()

    def user_hwid(self, user_id: int) -> bytes:
        row = self._c().execute(
            "SELECT lastHWID FROM User WHERE userID = ?", (user_id,)
        ).fetchone()
        return bytes(row[0]) if row and row[0] else b""

    # ---- 写入：道具 ----
    def _free_slot(self, user_id: int) -> int | None:
        row = self._c().execute(
            "SELECT slot FROM UserInventory WHERE userID = ? AND itemID = 0 LIMIT 1",
            (user_id,),
        ).fetchone()
        return int(row[0]) if row else None

    def _alloc_slot(self, user_id: int) -> int:
        slot = self._free_slot(user_id)
        if slot is not None:
            return slot
        row = self._c().execute(
            "SELECT nextInventorySlot FROM UserCharacterExtended WHERE userID = ? LIMIT 1",
            (user_id,),
        ).fetchone()
        slot = int(row[0]) if row and row[0] else 1
        self._c().execute(
            "INSERT INTO UserInventory (userID, slot, itemID, count, status, inUse,"
            " obtainDate, expiryDate, isClanItem, enhancementLevel, enhancementExp,"
            " enhanceValue, paintID, paintIDList, partSlot1, partSlot2, lockStatus)"
            " VALUES (?, ?, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, '', 0, 0, 0)",
            (user_id, slot),
        )
        self._c().execute(
            "UPDATE UserCharacterExtended SET nextInventorySlot = nextInventorySlot + 1"
            " WHERE userID = ?",
            (user_id,),
        )
        return slot

    def add_item(
        self, user_id: int, item: Item, count: int = 1, days: int = 0
    ) -> tuple[bool, str]:
        """离线发放，返回 (成功, 说明)。规则与服务端 AddItem 一致。"""
        c = self._c()
        count = max(1, int(count))
        days = max(0, int(days))
        slot_max = self.slot_max_default

        if self.inventory_count(user_id) >= slot_max:
            return False, f"背包已满（{slot_max}）"

        ts = now_minutes()

        # 规则 6：密码箱不占槽位
        if item.id == PASSWORD_BOX_ITEM:
            c.execute(
                "UPDATE UserCharacter SET passwordBoxes = passwordBoxes + ?"
                " WHERE userID = ?",
                (count, user_id),
            )
            c.commit()
            return True, f"密码箱 +{count}（累加到 passwordBoxes，不占背包槽）"

        exists = c.execute(
            "SELECT * FROM UserInventory WHERE userID = ? AND itemID = ? LIMIT 1",
            (user_id, item.id),
        ).fetchone()

        # 规则 3：可堆叠道具累加
        if item.stackable and exists:
            c.execute(
                "UPDATE UserInventory SET count = count + ? WHERE userID = ? AND slot = ?",
                (count, user_id, exists["slot"]),
            )
            c.commit()
            return True, f"已堆叠：{item.display_name} +{count}（槽 {exists['slot']}）"

        # 规则 5：已永久持有 + 要发限时 → 延长
        if exists and days:
            ext = c.execute(
                "SELECT * FROM UserInventory WHERE userID = ? AND itemID = ?"
                " AND expiryDate != 0 AND enhanceValue = 0 AND partSlot1 = 0"
                " AND partSlot2 = 0 LIMIT 1",
                (user_id, item.id),
            ).fetchone()
            if ext:
                new_expiry = int(ext["expiryDate"]) + days * CSO_24_HOURS_IN_MINUTES
                c.execute(
                    "UPDATE UserInventory SET expiryDate = ? WHERE userID = ? AND slot = ?",
                    (new_expiry, user_id, ext["slot"]),
                )
                c.commit()
                return True, (
                    f"已延长：{item.display_name} 至 {minutes_to_str(new_expiry)}"
                    f"（槽 {ext['slot']}）"
                )

        # 规则 2 + 4：新建行（永久）或限时行
        status, in_use = 1, 1
        expiry = ts + days * CSO_24_HOURS_IN_MINUTES if days else 0
        if exists and not item.stackable:
            # 已有同 ID 行时，新行不能同时处于启用态
            status, in_use = 1, 0

        slot = self._alloc_slot(user_id)
        c.execute(
            "UPDATE UserInventory SET itemID = ?, count = ?, status = ?, inUse = ?,"
            " obtainDate = ?, expiryDate = ?, isClanItem = 0, enhancementLevel = 0,"
            " enhancementExp = 0, enhanceValue = 0, paintID = 0, paintIDList = '',"
            " partSlot1 = 0, partSlot2 = 0, lockStatus = 2"
            " WHERE userID = ? AND slot = ?",
            (item.id, count, status, in_use, ts, expiry, user_id, slot),
        )
        c.commit()

        note = f"已发放：{item.display_name} ×{count}"
        note += f"，{minutes_to_str(expiry)} 到期" if expiry else "，永久"
        note += f"（槽 {slot}）"
        if item.special_note:
            note += f"\n注意：{item.special_note}"
        if item.is_costume:
            note += "\n注意：装扮需在「装扮」页设为穿戴才会生效"
        return True, note

    def remove_slot(self, user_id: int, slot: int) -> tuple[bool, str]:
        """按槽位清空道具。服务端用 itemID=0 的空行占位，不是 DELETE。"""
        c = self._c()
        row = c.execute(
            "SELECT * FROM UserInventory WHERE userID = ? AND slot = ?",
            (user_id, slot),
        ).fetchone()
        if not row or not row["itemID"]:
            return False, "该槽位没有道具"
        c.execute(
            "UPDATE UserInventory SET itemID = 0, count = 0, status = 0, inUse = 0,"
            " obtainDate = 0, expiryDate = 0, isClanItem = 0, enhancementLevel = 0,"
            " enhancementExp = 0, enhanceValue = 0, paintID = 0, paintIDList = '',"
            " partSlot1 = 0, partSlot2 = 0, lockStatus = 0"
            " WHERE userID = ? AND slot = ?",
            (user_id, slot),
        )
        c.commit()
        return True, f"已清空槽 {slot}（itemID {row['itemID']}）"

    def set_item_expiry(self, user_id: int, slot: int, days: int) -> tuple[bool, str]:
        c = self._c()
        row = c.execute(
            "SELECT expiryDate FROM UserInventory WHERE userID = ? AND slot = ?",
            (user_id, slot),
        ).fetchone()
        if not row:
            return False, "槽位不存在"
        new_expiry = 0 if days <= 0 else now_minutes() + days * CSO_24_HOURS_IN_MINUTES
        c.execute(
            "UPDATE UserInventory SET expiryDate = ? WHERE userID = ? AND slot = ?",
            (new_expiry, user_id, slot),
        )
        c.commit()
        return True, f"槽 {slot} 到期时间 → {minutes_to_str(new_expiry)}"

    # ---- 装扮 ----
    COSTUME_COLUMNS = {
        "HeadCostume": "head", "BackCostume": "back", "ArmCostume": "arm",
        "PelvisCostume": "pelvis", "FaceCostume": "face", "Tattoo": "tattoo",
        "PetCostume": "pet",
    }

    def costume_loadout(self, user_id: int) -> dict[str, int]:
        row = self._c().execute(
            "SELECT * FROM UserCostumeLoadout WHERE userID = ?", (user_id,)
        ).fetchone()
        if not row:
            return {}
        return {k: int(row[k] or 0) for k in
                ("head", "back", "arm", "pelvis", "face", "tattoo", "pet")}

    def zb_costume_loadout(self, user_id: int) -> dict[int, int]:
        rows = self._c().execute(
            "SELECT slot, itemID FROM UserZBCostumeLoadout WHERE userID = ?", (user_id,)
        )
        return {int(r["slot"]): int(r["itemID"]) for r in rows}

    def set_costume(self, user_id: int, column: str, item_id: int) -> tuple[bool, str]:
        if column not in ("head", "back", "arm", "pelvis", "face", "tattoo", "pet"):
            return False, f"未知装扮位：{column}"
        c = self._c()
        row = c.execute(
            "SELECT 1 FROM UserCostumeLoadout WHERE userID = ?", (user_id,)
        ).fetchone()
        if row:
            c.execute(
                f"UPDATE UserCostumeLoadout SET {column} = ? WHERE userID = ?",
                (item_id, user_id),
            )
        else:
            c.execute(
                "INSERT INTO UserCostumeLoadout (userID, head, back, arm, pelvis,"
                " face, tattoo, pet) VALUES (?, 0, 0, 0, 0, 0, 0, 0)",
                (user_id,),
            )
            c.execute(
                f"UPDATE UserCostumeLoadout SET {column} = ? WHERE userID = ?",
                (item_id, user_id),
            )
        c.commit()
        return True, f"已设置 {column} = {item_id}"

    def set_zb_costume(self, user_id: int, slot: int, item_id: int) -> tuple[bool, str]:
        c = self._c()
        row = c.execute(
            "SELECT 1 FROM UserZBCostumeLoadout WHERE userID = ? AND slot = ?",
            (user_id, slot),
        ).fetchone()
        if item_id == 0:
            c.execute(
                "DELETE FROM UserZBCostumeLoadout WHERE userID = ? AND slot = ?",
                (user_id, slot),
            )
        elif row:
            c.execute(
                "UPDATE UserZBCostumeLoadout SET itemID = ? WHERE userID = ? AND slot = ?",
                (item_id, user_id, slot),
            )
        else:
            c.execute(
                "INSERT INTO UserZBCostumeLoadout VALUES (?, ?, ?)",
                (user_id, slot, item_id),
            )
        c.commit()
        return True, f"已设置生化皮肤槽 {slot} = {item_id}"


__all__ = [
    "Database", "User", "InventoryRow", "now_minutes", "minutes_to_str",
    "days_left", "CSO_24_HOURS_IN_MINUTES", "PASSWORD_BOX_ITEM",
]
