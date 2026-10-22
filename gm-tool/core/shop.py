"""Shop.json 读写与校验。

服务端 CShopManager::LoadProducts 的行为决定了这些硬约束：

1. Version 必须 == 1（SHOP_JSON_VERSION）。不匹配 → LoadProducts 返回 false →
   dbreload 时 ReloadAll 失败 → CommandDbReload 会 SetServerActive(false) 直接关服。
2. 子规格 ID 是加载时按 JSON 顺序自增分配（productTypeId 从 1 开始跨商品连续），
   所以保存后必须 reload；顺序变了子规格 ID 就会整体位移。
3. 一个子规格只卖一件道具：代码解析 Items[] 数组，但 SendShopUpdate 只下发 items[0]。
   因此本工具不允许在子规格里配多件道具，要做礼包请走 ItemRewards.json + givereward。
4. Products 的键是 itemID；Recommended 是 {页号: [itemID...]}；Popular 是 [itemID...]。
"""
from __future__ import annotations

import json
import shutil
from datetime import datetime
from pathlib import Path

SHOP_JSON_VERSION = 1

# 字段取值范围来自 CPacketManager::SendShopUpdate 的实际写入宽度：
#   productID         UInt32
#   duration          Int16   （服务端只下发 items[0].duration）
#   count             UInt16
#   price             UInt32
#   additionalPoints  UInt32
#   adType            UInt8
# 超出宽度会被静默截断，表现为「填了 70000 结果客户端显示 4464」，必须前置拦截。
FIELD_LIMITS = {
    "count": (1, 65535, "数量"),
    "duration": (0, 32767, "天数（0=永久）"),
    "price": (0, 4294967295, "价格"),
    "add_points": (0, 4294967295, "返点"),
    "add_clan_points": (0, 4294967295, "返公会点"),
    "ad_type": (0, 255, "角标"),
}

# 这些字段解析了但服务端从不使用，界面上要标出来
INERT_FIELDS = {
    "add_clan_points": "服务端只解析和回写，既不下发给客户端，也不参与购买结算，填了无效",
}


class SubProduct:
    __slots__ = ("index", "count", "duration", "price",
                 "add_points", "add_clan_points", "ad_type", "items")

    def __init__(self, index: int, data: dict) -> None:
        self.index = index
        self.count = int(data.get("Count", 1) or 1)
        self.duration = int(data.get("Duration", 0) or 0)
        self.price = int(data.get("Price", 0) or 0)
        self.add_points = int(data.get("AdditionalPoints", 0) or 0)
        self.add_clan_points = int(data.get("AdditionalClanPoints", 0) or 0)
        self.ad_type = int(data.get("AdType", 0) or 0)
        # 源文件里可能残留 Items[]，但服务端只下发第一件，这里只用于告警
        self.items = data.get("Items") or {}

    def to_dict(self) -> dict:
        return {
            "Count": self.count,
            "Duration": self.duration,
            "Price": self.price,
            "AdditionalPoints": self.add_points,
            "AdditionalClanPoints": self.add_clan_points,
            "AdType": self.ad_type,
        }

    def describe(self) -> str:
        dur = f"{self.duration} 天" if self.duration else "永久"
        cur = ""
        return f"{self.count} 个 / {dur} / {self.price} 点券"


class ShopProduct:
    __slots__ = ("item_id", "is_points", "subs")

    def __init__(self, item_id: int, is_points: bool, subs: list[SubProduct]) -> None:
        self.item_id = item_id
        self.is_points = is_points
        self.subs = subs

    def to_dict(self) -> dict:
        # 子规格键必须是 0..n-1 连续：服务端按顺序自增分配 productTypeId，
        # 键不连续本身不会报错，但会让「界面上第几档」与「客户端第几档」对不上。
        return {
            "IsPoints": self.is_points,
            "SubProducts": {
                str(i): sub.to_dict() for i, sub in enumerate(self.subs)
            },
        }


class Shop:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.version = SHOP_JSON_VERSION
        self.products: dict[int, ShopProduct] = {}
        self.recommended: dict[str, list[int]] = {}
        self.popular: list[int] = []
        self.dirty = False

    # ---- 读写 ----
    def load(self) -> None:
        raw = self.path.read_text(encoding="utf-8-sig")
        data = json.loads(raw)
        self.version = int(data.get("Version", 0))
        self.products.clear()
        for key, prod in (data.get("Products") or {}).items():
            subs: list[SubProduct] = []
            for sidx, sub in (prod.get("SubProducts") or {}).items():
                subs.append(SubProduct(int(sidx), sub))
            subs.sort(key=lambda s: s.index)
            self.products[int(key)] = ShopProduct(
                int(key), bool(prod.get("IsPoints", False)), subs
            )
        self.recommended = {
            str(k): [int(x) for x in v]
            for k, v in (data.get("Recommended") or {}).items()
        }
        self.popular = [int(x) for x in (data.get("Popular") or [])]
        self.dirty = False

    def to_dict(self) -> dict:
        return {
            "Version": SHOP_JSON_VERSION,
            "Recommended": self.recommended,
            "Popular": self.popular,
            "Products": {
                str(pid): p.to_dict()
                for pid, p in sorted(self.products.items())
            },
        }

    def save(self, backup_dir: Path | None = None,
             known_item_ids: set[int] | None = None) -> Path | None:
        """先自校验再落盘，并保留备份。返回备份路径（若有）。"""
        problems = self.validate(known_item_ids)
        if problems:
            raise ValueError("商城配置校验失败：\n" + "\n".join(problems))
        backup = None
        if backup_dir:
            backup_dir.mkdir(parents=True, exist_ok=True)
            stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            backup = backup_dir / f"Shop_{stamp}.json"
            if self.path.exists():
                shutil.copy2(self.path, backup)
        text = json.dumps(self.to_dict(), ensure_ascii=False, indent="\t")
        self.path.write_text(text + "\n", encoding="utf-8")
        self.dirty = False
        return backup

    # ---- 校验 ----
    def validate(self, known_item_ids: set[int] | None = None) -> list[str]:
        """known_item_ids 传入 Item.csv 的有效 ID 集合时，会校验上架道具是否存在。

        上架不存在的 itemID 时服务端不会报错，但玩家购买会收到
        BUY_FAIL_SYSTEM_ERROR（AddItem 返回 ITEM_ADD_UNKNOWN_ITEMID），
        因此这一项必须在保存前拦住。
        """
        problems: list[str] = []
        if not self.products:
            problems.append("商城为空：至少要有 1 个商品，否则客户端商城页会空白")
        for pid, prod in self.products.items():
            if pid <= 0:
                problems.append(f"商品 {pid}：itemID 必须为正整数")
            elif known_item_ids is not None and pid not in known_item_ids:
                problems.append(
                    f"商品 {pid}：Item.csv 里没有这个道具，玩家购买会失败"
                )
            if not prod.subs:
                problems.append(f"商品 {pid}：没有子规格，将无法购买")
            if len(prod.subs) > 20:
                problems.append(f"商品 {pid}：子规格超过 20 个")
            for sub in prod.subs:
                for key in ("count", "duration", "price", "add_points",
                            "add_clan_points", "ad_type"):
                    lo, hi, label = FIELD_LIMITS[key]
                    val = getattr(sub, key)
                    if not (lo <= val <= hi):
                        problems.append(
                            f"商品 {pid}/{sub.index}：{label} {val} 超出 "
                            f"{lo} ~ {hi}，会被服务端截断"
                        )
                if len(sub.items) > 1:
                    problems.append(
                        f"商品 {pid}/{sub.index}：配了多件道具，服务端只会下发第一件"
                    )
        for page, ids in self.recommended.items():
            for iid in ids:
                if iid not in self.products:
                    problems.append(f"推荐位页 {page}：itemID {iid} 不在商品列表里")
        for iid in self.popular:
            if iid not in self.products:
                problems.append(f"热销位：itemID {iid} 不在商品列表里")
        return problems

    # ---- 编辑 ----
    def upsert_product(self, item_id: int, is_points: bool,
                       subs: list[SubProduct]) -> None:
        self.products[item_id] = ShopProduct(item_id, is_points, subs)
        self.dirty = True

    def remove_product(self, item_id: int) -> None:
        self.products.pop(item_id, None)
        for page in self.recommended.values():
            while item_id in page:
                page.remove(item_id)
        self.popular = [x for x in self.popular if x != item_id]
        self.dirty = True

    # ---- 子规格编辑 ----
    def get_sub(self, item_id: int, sub_index: int) -> SubProduct | None:
        prod = self.products.get(item_id)
        if not prod:
            return None
        for sub in prod.subs:
            if sub.index == sub_index:
                return sub
        return None

    def update_sub(self, item_id: int, sub_index: int, **fields) -> bool:
        """就地修改子规格字段。

        允许的字段与 Shop.json 的 SubProduct 结构一一对应；
        非法值直接拒绝，不做静默纠正，避免把坏数据写进商城。
        """
        allowed = {"count", "duration", "price", "add_points",
                   "add_clan_points", "ad_type"}
        sub = self.get_sub(item_id, sub_index)
        if sub is None:
            return False
        for key, raw in fields.items():
            if key not in allowed:
                continue
            try:
                val = int(raw)
            except (TypeError, ValueError):
                raise ValueError(f"{FIELD_LIMITS.get(key, (0, 0, key))[2]} 必须是整数")
            lo, hi, label = FIELD_LIMITS.get(key, (0, 4294967295, key))
            if not (lo <= val <= hi):
                raise ValueError(f"{label} 必须在 {lo} ~ {hi} 之间（当前 {val}）")
            setattr(sub, key, val)
        self.dirty = True
        return True

    def add_sub(self, item_id: int, count: int = 1, duration: int = 30,
                price: int = 1000, add_points: int = 0,
                add_clan_points: int = 0, ad_type: int = 0) -> SubProduct | None:
        """追加一个子规格，index 取当前最大值 +1。

        index 只用于本文件内部的稳定排序，落盘时统一按顺序重排为 0..n-1，
        真正下发给客户端的子规格 ID 由服务端按顺序自增分配。
        """
        prod = self.products.get(item_id)
        if prod is None:
            return None
        for key, val in (("count", count), ("duration", duration), ("price", price),
                         ("add_points", add_points),
                         ("add_clan_points", add_clan_points), ("ad_type", ad_type)):
            lo, hi, label = FIELD_LIMITS[key]
            if not (lo <= int(val) <= hi):
                raise ValueError(f"{label} 必须在 {lo} ~ {hi} 之间（当前 {val}）")
        next_idx = (max((s.index for s in prod.subs), default=-1) + 1)
        sub = SubProduct(next_idx, {
            "Count": count, "Duration": duration, "Price": price,
            "AdditionalPoints": add_points, "AdditionalClanPoints": add_clan_points,
            "AdType": ad_type,
        })
        prod.subs.append(sub)
        self.dirty = True
        return sub

    def remove_sub(self, item_id: int, sub_index: int) -> bool:
        prod = self.products.get(item_id)
        if not prod:
            return False
        before = len(prod.subs)
        prod.subs = [s for s in prod.subs if s.index != sub_index]
        if len(prod.subs) == before:
            return False
        self.dirty = True
        return True

    def duplicate_sub(self, item_id: int, sub_index: int) -> SubProduct | None:
        src = self.get_sub(item_id, sub_index)
        if src is None:
            return None
        return self.add_sub(item_id, src.count, src.duration, src.price,
                            src.add_points, src.add_clan_points, src.ad_type)

    def set_currency(self, item_id: int, is_points: bool) -> bool:
        prod = self.products.get(item_id)
        if not prod:
            return False
        prod.is_points = bool(is_points)
        self.dirty = True
        return True

    def toggle_popular(self, item_id: int) -> None:
        if item_id in self.popular:
            self.popular.remove(item_id)
        else:
            self.popular.append(item_id)
        self.dirty = True

    def toggle_recommended(self, page: str, item_id: int) -> None:
        page_list = self.recommended.setdefault(page, [])
        if item_id in page_list:
            page_list.remove(item_id)
        else:
            page_list.append(item_id)
        self.dirty = True

    # ---- 统计 ----
    def stats(self) -> dict:
        sub_total = sum(len(p.subs) for p in self.products.values())
        return {
            "products": len(self.products),
            "subproducts": sub_total,
            "recommended_pages": len(self.recommended),
            "popular": len(self.popular),
            "version_ok": self.version == SHOP_JSON_VERSION,
        }


__all__ = ["Shop", "ShopProduct", "SubProduct", "SHOP_JSON_VERSION"]
