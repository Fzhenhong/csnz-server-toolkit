"""道具主表：Item.csv（EUC-KR，57 列）+ 客户端语言包中文名合并。

Item.csv 的 Name 列全是英文内部名，中文名只存在于客户端语言包
（cso_chn.txt，UTF-16LE + BOM，KeyValues 格式），键名规则为 CSO_<Name>。
两者都不是可靠来源，因此再叠加一份工具侧别名表 item_aliases.json
（手工维护，不改动 Item.csv，避免影响下发给客户端的 metadata）。
"""
from __future__ import annotations

import csv
import io
import json
import re
from pathlib import Path

# 与源码 CItemManager::AddItem 判定相关的列
COL_ID = "ID"
COL_NAME = "Name"
COL_CLASS = "ClassName"
COL_RES = "recourcename"
COL_CATEGORY = "Category"
COL_USETYPE = "UseType"
COL_GRADE = "ItemGrade"
COL_PERIOD = "Period"
COL_EXTEND = "CanExtend"

CATEGORY_NAMES = {
    "1": "手枪", "2": "霰弹枪", "3": "冲锋枪", "4": "步枪", "5": "机枪",
    "6": "装备", "7": "角色", "8": "功能性", "9": "消耗品", "11": "近战",
    "12": "装扮", "13": "武器部件", "14": "战术装备", "15": "技能", "16": "ClassMod",
}

USETYPE_NAMES = {
    "0": "间接使用", "1": "自动使用", "2": "手动使用",
    "3": "手动(int)", "4": "手动(string)", "5": "弹窗", "6": "不可用",
}

# 源码里被特殊处理的道具，工具必须知道，否则改库会与服务端不一致
SPECIAL_ITEMS = {
    166: "密码箱：不占背包槽，改为累加 UserCharacter.passwordBoxes",
    676: "道具延长器",
    8357: "超级房卡：加入时给房主设置 superRoom 标记",
    439: "大头模式：加入时给房主设置 sd 标记",
    112: "C4 音效：加入时给房主设置 c4Timer 标记",
}


def is_stackable(category: int, use_type: int) -> bool:
    """复刻 AddItem 的可堆叠判定：走 count 累加而不是新建行。"""
    return (category == 9 and use_type in (0, 1, 2)) or (
        category == 8 and use_type in (0, 2)
    )


class Item:
    """一条道具记录。只保留工具真正用到的列，避免 57 列全部驻留。"""

    __slots__ = (
        "id", "name", "class_name", "resource_name", "category", "use_type",
        "grade", "period", "can_extend", "cn_name", "alias",
    )

    def __init__(self, row: list[str], idx: dict[str, int]) -> None:
        self.id = int(row[idx[COL_ID]])
        self.name = row[idx[COL_NAME]].strip()
        self.class_name = row[idx[COL_CLASS]].strip()
        self.resource_name = row[idx[COL_RES]].strip()
        cat = row[idx[COL_CATEGORY]].strip()
        self.category = int(cat) if cat.lstrip("-").isdigit() else 0
        ut = row[idx[COL_USETYPE]].strip()
        self.use_type = int(ut) if ut.lstrip("-").isdigit() else 0
        g = row[idx[COL_GRADE]].strip()
        self.grade = int(g) if g.lstrip("-").isdigit() else 0
        p = row[idx[COL_PERIOD]].strip()
        self.period = int(p) if p.lstrip("-").isdigit() else 0
        ce = row[idx[COL_EXTEND]].strip()
        self.can_extend = int(ce) if ce.lstrip("-").isdigit() else 0
        self.cn_name = ""
        self.alias = ""

    # ---- 展示用 ----
    @property
    def display_name(self) -> str:
        return self.alias or self.cn_name or self.name

    @property
    def category_name(self) -> str:
        return CATEGORY_NAMES.get(str(self.category), f"其他({self.category})")

    @property
    def stackable(self) -> bool:
        return is_stackable(self.category, self.use_type)

    @property
    def is_costume(self) -> bool:
        return self.category == 12 or self.class_name == "Tattoo"

    @property
    def special_note(self) -> str:
        return SPECIAL_ITEMS.get(self.id, "")

    def matches(self, needle: str) -> bool:
        n = needle.lower()
        for field in (self.name, self.class_name, self.cn_name, self.alias,
                      self.resource_name, self.category_name):
            if n in field.lower():
                return True
        return n == str(self.id)


class ItemDB:
    """全量道具索引，加载一次即可服务所有界面。"""

    def __init__(self) -> None:
        self.items: dict[int, Item] = {}
        self.categories: dict[int, str] = {}
        self.lang_missing = False
        self.errors: list[str] = []

    def __len__(self) -> int:
        return len(self.items)

    def get(self, item_id: int) -> Item | None:
        return self.items.get(item_id)

    def load(self, item_csv: Path, lang_file: Path | None) -> None:
        self.items.clear()
        self.errors.clear()

        raw = item_csv.read_bytes()
        text = raw.decode("euc-kr", errors="replace")
        rows = list(csv.reader(io.StringIO(text)))
        if len(rows) < 3:
            raise ValueError(f"{item_csv.name} 行数异常：{len(rows)}")

        # 第 0 行是说明、第 1 行才是列头（首列带 ; 前缀）
        header = [c.lstrip(";").strip() for c in rows[1]]
        idx = {h: i for i, h in enumerate(header)}
        for need in (COL_ID, COL_NAME, COL_CLASS, COL_CATEGORY, COL_USETYPE):
            if need not in idx:
                raise ValueError(f"{item_csv.name} 缺少列 {need}")

        width = len(header)
        for row in rows[2:]:
            if not row or not row[0] or row[0].startswith(";"):
                continue
            if len(row) != width:
                continue  # 列数不符的行直接跳过，保持与 csvtable 一致
            try:
                item = Item(row, idx)
            except (ValueError, IndexError):
                continue
            self.items[item.id] = item

        tokens = self._load_lang(lang_file)
        self.lang_missing = not tokens
        generic = self._generic_class_names()
        for item in self.items.values():
            item.cn_name = self._resolve_name(item, tokens, generic)
        self.categories = CATEGORY_NAMES

    def _generic_class_names(self, threshold: int = 3) -> set[str]:
        """找出被大量道具共用的 ClassName。

        Item.csv 的 ClassName 多数是类别名（Equipment / RewardItem / PeriodicItem…），
        语言包里恰好也有 CSO_Equipment="装备" 这类词条。若直接拿 ClassName 去查，
        所有武器都会被显示成「装备」，比不翻译更糟，因此按出现频次过滤掉。
        """
        counter: dict[str, int] = {}
        for item in self.items.values():
            if item.class_name:
                counter[item.class_name] = counter.get(item.class_name, 0) + 1
        return {c for c, n in counter.items() if n > threshold}

    @staticmethod
    def _resolve_name(item: "Item", tokens: dict[str, str],
                      generic: set[str]) -> str:
        """按 Name → recourcename → ClassName（仅非通用类名）的顺序取中文名。"""
        for key in ("CSO_" + item.name, "CSO_" + item.resource_name):
            val = tokens.get(key)
            if val and val.strip():
                return val.strip()
        if item.class_name and item.class_name not in generic:
            val = tokens.get("CSO_" + item.class_name)
            if val and val.strip():
                return val.strip()
        return ""

    @staticmethod
    def _load_lang(lang_file: Path | None) -> dict[str, str]:
        if not lang_file or not lang_file.exists():
            return {}
        raw = lang_file.read_bytes()
        text = raw.decode("utf-16-le", errors="replace")
        if text and text[0] == "\ufeff":
            text = text[1:]
        pat = re.compile(r'"([A-Za-z0-9_\-\.]+)"\s+"((?:[^"\\]|\\.)*)"')
        return dict(pat.findall(text))

    # ---- 别名表 ----
    def load_aliases(self, path: Path) -> None:
        if not path.exists():
            return
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception as e:
            self.errors.append(f"别名表读取失败：{e}")
            return
        for k, v in data.items():
            item = self.items.get(int(k))
            if item and v:
                item.alias = str(v)

    def save_aliases(self, path: Path) -> None:
        data = {
            str(i.id): i.alias for i in self.items.values() if i.alias
        }
        path.write_text(
            json.dumps(data, ensure_ascii=False, indent=1, sort_keys=True),
            encoding="utf-8",
        )

    # ---- 检索 ----
    def search(
        self,
        needle: str = "",
        category: int | None = None,
        stackable_only: bool = False,
        max_results: int = 3000,
    ) -> list[Item]:
        out: list[Item] = []
        needle = needle.strip()
        for item in self.items.values():
            if category is not None and item.category != category:
                continue
            if stackable_only and not item.stackable:
                continue
            if needle and not (
                item.matches(needle) or str(item.id).zfill(4).startswith(needle)
            ):
                continue
            out.append(item)
            if len(out) >= max_results:
                break
        out.sort(key=lambda i: i.id)
        return out


__all__ = [
    "Item", "ItemDB", "CATEGORY_NAMES", "USETYPE_NAMES", "SPECIAL_ITEMS",
    "is_stackable", "COL_ID", "COL_NAME", "COL_CLASS", "COL_CATEGORY", "COL_USETYPE",
]
