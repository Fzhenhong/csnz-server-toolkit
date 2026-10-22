"""商城管理页。

硬约束（全部来自 CShopManager / CommandShopReload 源码，已实测验证）：

1. shopreload 是坏的，不能用来刷新商城。
   CommandShopReload 直接调 g_ShopManager.Init()，而 m_Products.clear() 只在
   Shutdown() 里做，所以每执行一次商品就在旧列表后面再追加一遍。
   实测：47 → 94 → 141 → 188。后果是客户端商城出现重复商品、子规格 ID 错位，
   玩家可能买到错的东西。
   唯一正确的热重载是 dbreload：CManager::ReloadAll() 先 Shutdown() 再 Init()，
   实测能让商品数回到 47。

2. Version 必须为 1，否则 LoadProducts 返回 false，
   dbreload 时 ReloadAll 失败 → CServerInstance 主动 SetServerActive(false) 关服。

3. 子规格 ID 由加载顺序自增分配，因此改完必须重载。

4. 一个子规格只能卖一件道具（SendShopUpdate 只下发 items[0]），
   礼包要走 ItemRewards.json + givereward。

5. 子规格的 index 只是工具内部排序用，落盘时统一重排为 0..n-1；
   客户端看到的档位顺序就是 JSON 里的顺序，因此「改数量/价格」不需要
   动 index，只有「增删档位」才会让后续档位的客户端 ID 位移。
   既然任何保存都要 dbreload，位移不会造成错配，但**绝不能在未重载的
   情况下让玩家购买**——这正是保存后强制提示重载的原因。
"""

from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, ttk

from core import audit
from core.shop import FIELD_LIMITS, INERT_FIELDS
from . import theme

P = theme.px


class ShopTab(ttk.Frame):
    """上半是商品表，下半是该商品的子规格表（数量/天数/价格/返点/角标全可改）。"""

    def __init__(self, master, app) -> None:
        super().__init__(master, padding=10)
        self.app = app
        self._product_id: int | None = None
        self._sub_index: int | None = None
        self._pending_reload = False

        self._build()
        self.refresh()

    # ---- 布局 ----
    def _build(self) -> None:
        outer, acts = theme.page(
            self, "商城管理",
            "商品与档位（子规格）编辑。改动保存后必须 dbreload 才会同步到客户端。")
        theme.button(acts, "刷新", "ghost", self.refresh).pack(side="right")
        self.reload_btn = theme.button(acts, "重新加载商城", "default",
                                       self._reload_shop)
        self.reload_btn.pack(side="right", padx=(0, P(7)))
        self.save_btn = theme.button(acts, "保存 Shop.json", "primary", self._save)
        self.save_btn.pack(side="right", padx=(0, P(7)))

        # 已知缺陷提示
        warn = tk.Frame(outer, bg="#1e1a12", highlightthickness=1,
                        highlightbackground="#4a3a1c")
        warn.pack(fill="x", pady=(P(12), 0))
        tk.Frame(warn, bg=theme.WARN, width=P(2)).pack(side="left", fill="y")
        tk.Label(
            warn,
            text="不要用 shopreload——它不会清空旧列表，每执行一次商品就重复追加"
                 "（47 → 94 → 141 → 188），客户端会出现重复商品与错位档位。"
                 "唯一正确的热重载是 dbreload。",
            font=theme.FONT_XS, fg="#e8c88d", bg="#1e1a12", justify="left",
            anchor="w", wraplength=P(900),
        ).pack(side="left", fill="x", expand=True, padx=P(10), pady=P(7))

        wrap = tk.Frame(outer, bg=theme.L0)
        wrap.pack(fill="both", expand=True, pady=(P(12), 0))
        wrap.columnconfigure(0, weight=1)
        wrap.rowconfigure(0, weight=155)
        wrap.rowconfigure(2, weight=100)

        # ---- 商品表 ----
        pc = theme.Card(wrap, "商品", padding=0)
        pc.grid(row=0, column=0, sticky="nsew")
        self.stat_label = tk.Label(pc.head, text="", font=theme.FONT_S,
                                   fg=theme.FG3, bg=theme.L2)
        self.stat_label.pack(side="right", padx=(0, P(12)))
        self.table = theme.Table(
            pc.body,
            [("id", "itemID", 72), ("name", "道具名", 200, "w", True),
             ("cur", "货币", 58), ("subs", "档位", 50, "e"),
             ("price", "价格区间", 118, "e"), ("tag", "陈列", 140)],
            height=6, on_select=self._on_product_select,
        )
        self.table.pack(fill="both", expand=True, padx=1, pady=(0, 1))

        # ---- 商品操作条 ----
        pbar = tk.Frame(wrap, bg=theme.L0)
        pbar.grid(row=1, column=0, sticky="ew", pady=(P(10), 0))
        tk.Label(pbar, text="itemID", font=theme.FONT_XS, fg=theme.FG3,
                 bg=theme.L0).pack(side="left")
        self.new_id = tk.StringVar()
        ttk.Entry(pbar, textvariable=self.new_id, width=8).pack(
            side="left", padx=(P(5), P(7)))
        self.new_currency = tk.StringVar(value="点券")
        ttk.Combobox(pbar, textvariable=self.new_currency,
                     values=["点券", "现金"], width=6,
                     state="readonly").pack(side="left")
        theme.button(pbar, "上架 / 覆盖", "default", self._upsert).pack(
            side="left", padx=(P(7), 0))
        theme.button(pbar, "删除商品", "danger", self._delete).pack(
            side="left", padx=(P(6), 0))

        tk.Frame(pbar, bg=theme.LINE, width=P(1)).pack(side="left", fill="y",
                                                       padx=P(12), pady=P(2))
        tk.Label(pbar, text="货币", font=theme.FONT_XS, fg=theme.FG3,
                 bg=theme.L0).pack(side="left")
        self.cur_var = tk.StringVar(value="点券")
        cb = ttk.Combobox(pbar, textvariable=self.cur_var,
                          values=["点券", "现金"], width=6, state="readonly")
        cb.pack(side="left", padx=(P(5), 0))
        cb.bind("<<ComboboxSelected>>", lambda e: self._set_currency())
        theme.button(pbar, "切换热销", "default", self._toggle_popular).pack(
            side="left", padx=(P(6), 0))
        theme.button(pbar, "切换推荐", "default",
                     lambda: self._toggle_rec("0")).pack(side="left", padx=(P(6), 0))

        # ---- 档位 ----
        sc = theme.Card(wrap, "档位（子规格）", padding=0)
        sc.grid(row=2, column=0, sticky="nsew", pady=(P(12), 0))
        tk.Label(sc.head, text="一个档位只能卖一件道具", font=theme.FONT_S,
                 fg=theme.FG3, bg=theme.L2).pack(side="right", padx=(0, P(12)))
        self.sub_table = theme.Table(
            sc.body,
            [("idx", "#", 40, "e"), ("count", "数量", 66, "e"),
             ("days", "天数", 66, "e"), ("price", "价格", 88, "e"),
             ("adp", "返点", 66, "e"), ("adc", "返公会点", 84, "e"),
             ("adt", "角标", 60, "e")],
            height=4, on_select=self._on_sub_select,
            on_double=self._load_sub_to_form,
        )
        self.sub_table.pack(fill="both", expand=True, padx=1, pady=(0, 1))

        form = tk.Frame(sc, bg=theme.L2)
        form.pack(fill="x", padx=P(12), pady=P(10))

        self.f_count = tk.StringVar()
        self.f_days = tk.StringVar()
        self.f_price = tk.StringVar()
        self.f_adp = tk.StringVar()
        self.f_adc = tk.StringVar()
        self.f_adt = tk.StringVar()

        specs = [
            ("数量", self.f_count, 5, "1~65535"),
            ("天数", self.f_days, 5, "0=永久"),
            ("价格", self.f_price, 7, "按货币"),
            ("返点", self.f_adp, 5, "购买返还"),
            ("返公会点", self.f_adc, 5, "服务端不用"),
            ("角标", self.f_adt, 4, "0~255"),
        ]
        for label, var, width, note in specs:
            holder = tk.Frame(form, bg=theme.L2)
            holder.pack(side="left", padx=(0, P(8)))
            tk.Label(holder, text=label, font=theme.FONT_XS, fg=theme.FG3,
                     bg=theme.L2, anchor="w").pack(anchor="w")
            ttk.Entry(holder, textvariable=var, width=width).pack(pady=(P(2), 0))
            tk.Label(holder, text=note, font=theme.FONT_XS, fg="#5d6b7d",
                     bg=theme.L2, anchor="w").pack(anchor="w")

        btns = tk.Frame(form, bg=theme.L2)
        btns.pack(side="right")
        theme.button(btns, "应用到选中档", "primary", self._apply_sub).pack(
            side="left")
        theme.button(btns, "新增", "default", self._add_sub).pack(
            side="left", padx=(P(6), 0))
        theme.button(btns, "复制", "default", self._dup_sub).pack(
            side="left", padx=(P(6), 0))
        theme.button(btns, "删除", "danger", self._del_sub).pack(
            side="left", padx=(P(6), 0))

        self.hint = tk.Label(outer, text="", font=theme.FONT_XS, fg=theme.FG3,
                             bg=theme.L0, anchor="w", justify="left",
                             wraplength=P(1000))
        self.hint.pack(fill="x", pady=(P(8), 0))

    # ---- 刷新 ----
    def refresh(self) -> None:
        shop = self.app.shop
        rows = []
        for pid, prod in sorted(shop.products.items()):
            item = self.app.items.get(pid)
            name = item.display_name if item else "（Item.csv 中不存在）"
            prices = [s.price for s in prod.subs] or [0]
            price_txt = (f"{min(prices)}" if min(prices) == max(prices)
                         else f"{min(prices)} ~ {max(prices)}")
            tag = []
            if pid in shop.popular:
                tag.append("热销")
            for page, ids in shop.recommended.items():
                if pid in ids:
                    tag.append(f"推荐{page}")
            rows.append((pid, name, "点券" if prod.is_points else "现金",
                         len(prod.subs), price_txt, " ".join(tag)))
        self.table.set_rows(rows)

        st = shop.stats()
        self.stat_label.configure(
            text=f"商品 {st['products']} · 档位 {st['subproducts']} · "
                 f"推荐页 {st['recommended_pages']} · 热销 {st['popular']}"
        )
        self._refresh_subs()
        self._update_hint()

    def _refresh_subs(self) -> None:
        pid = self._product_id
        rows = []
        if pid is not None:
            prod = self.app.shop.products.get(pid)
            if prod:
                for sub in prod.subs:
                    rows.append((sub.index, sub.count, sub.duration, sub.price,
                                 sub.add_points, sub.add_clan_points, sub.ad_type))
        self.sub_table.set_rows(rows)

    def _update_hint(self) -> None:
        pid = self._product_id
        if self._pending_reload:
            self.hint.configure(
                text="⚠ 已修改但尚未重新加载：客户端看到的还是旧商城，"
                     "玩家此时购买会按旧价格结算。请点右上角「重新加载商城」。",
                fg=theme.DANGER,
            )
        elif pid is None:
            self.hint.configure(
                text="先在上方选择商品，再编辑它的档位。"
                     "数量=一次购买给几个；天数=有效期（0 表示永久）；价格=点券或现金。",
                fg=theme.FG3,
            )
        else:
            prod = self.app.shop.products.get(pid)
            cur = "点券" if prod and prod.is_points else "现金"
            self.hint.configure(
                text=(
                    f"当前商品 {pid} 的货币为「{cur}」，下表价格即按{cur}计价。"
                    f"改完记得保存 + 重新加载。\n"
                    f"「返公会点」服务端只解析不回写也不结算，填了无效；"
                    f"价格上限 4294967295、数量 65535、天数 32767、角标 255，"
                    f"超出会被服务端截断，工具已拦截。"
                ),
                style="Muted.TLabel",
            )

    # ---- 选中 ----
    def _on_product_select(self) -> None:
        row = self.table.selected_row()
        if not row:
            return
        pid = int(row[0])
        if pid != self._product_id:
            self._sub_index = None
            self._clear_form()
        self._product_id = pid
        self.new_id.set(str(pid))
        prod = self.app.shop.products.get(pid)
        if prod:
            self.cur_var.set("点券" if prod.is_points else "现金")
        self._refresh_subs()
        self._update_hint()

    def _on_sub_select(self) -> None:
        row = self.sub_table.selected_row()
        if not row:
            return
        self._sub_index = int(row[0])
        self._load_sub_to_form()

    def _load_sub_to_form(self) -> None:
        if self._product_id is None or self._sub_index is None:
            return
        sub = self.app.shop.get_sub(self._product_id, self._sub_index)
        if not sub:
            return
        self.f_count.set(str(sub.count))
        self.f_days.set(str(sub.duration))
        self.f_price.set(str(sub.price))
        self.f_adp.set(str(sub.add_points))
        self.f_adc.set(str(sub.add_clan_points))
        self.f_adt.set(str(sub.ad_type))

    def _clear_form(self) -> None:
        for var in (self.f_count, self.f_days, self.f_price,
                    self.f_adp, self.f_adc, self.f_adt):
            var.set("")

    def _form_values(self) -> dict:
        def as_int(var: tk.StringVar, label: str) -> int:
            raw = var.get().strip()
            if raw == "":
                raise ValueError(f"请填写{label}")
            return int(raw)

        return {
            "count": as_int(self.f_count, "数量"),
            "duration": as_int(self.f_days, "天数"),
            "price": as_int(self.f_price, "价格"),
            "add_points": as_int(self.f_adp, "返点") if self.f_adp.get().strip() else 0,
            "add_clan_points": (as_int(self.f_adc, "返公会点")
                                if self.f_adc.get().strip() else 0),
            "ad_type": as_int(self.f_adt, "角标") if self.f_adt.get().strip() else 0,
        }

    def _require_product(self) -> bool:
        if self._product_id is None:
            messagebox.showinfo("提示", "请先在上方选择一个商品")
            return False
        return True

    # ---- 子规格操作 ----
    def _apply_sub(self) -> None:
        if not self._require_product():
            return
        if self._sub_index is None:
            messagebox.showinfo("提示", "请先在下方表格选中一个档位（双击可载入表单）")
            return
        try:
            values = self._form_values()
            self.app.shop.update_sub(self._product_id, self._sub_index, **values)
        except ValueError as e:
            messagebox.showerror("输入错误", str(e))
            return
        audit.log(
            "修改商城档位",
            f"itemID {self._product_id} 档 {self._sub_index} → "
            f"数量{values['count']} 天数{values['duration']} "
            f"价格{values['price']} 返点{values['add_points']} "
            f"返公会点{values['add_clan_points']} 角标{values['ad_type']}",
        )
        self._pending_reload = True
        self.refresh()

    def _add_sub(self) -> None:
        if not self._require_product():
            return
        try:
            values = self._form_values()
        except ValueError:
            # 表单没填就按默认档位新增
            values = {"count": 1, "duration": 30, "price": 1000,
                      "add_points": 0, "add_clan_points": 0, "ad_type": 0}
        try:
            sub = self.app.shop.add_sub(self._product_id, **values)
        except ValueError as e:
            messagebox.showerror("输入错误", str(e))
            return
        if sub is None:
            messagebox.showerror("失败", "该商品不存在")
            return
        audit.log("新增商城档位",
                  f"itemID {self._product_id} 档 {sub.index} 价格 {sub.price}")
        self._pending_reload = True
        self._sub_index = sub.index
        self.refresh()

    def _dup_sub(self) -> None:
        if not self._require_product():
            return
        if self._sub_index is None:
            messagebox.showinfo("提示", "请先选中要复制的档位")
            return
        sub = self.app.shop.duplicate_sub(self._product_id, self._sub_index)
        if not sub:
            return
        audit.log("复制商城档位",
                  f"itemID {self._product_id} {self._sub_index} → {sub.index}")
        self._pending_reload = True
        self._sub_index = sub.index
        self.refresh()

    def _del_sub(self) -> None:
        if not self._require_product():
            return
        if self._sub_index is None:
            messagebox.showinfo("提示", "请先选中要删除的档位")
            return
        prod = self.app.shop.products.get(self._product_id)
        if prod and len(prod.subs) <= 1:
            messagebox.showerror(
                "不能删除",
                "商品至少要保留 1 个档位，否则玩家无法购买该商品。\n\n"
                "如果不想卖这个商品，请用「删除商品」。",
            )
            return
        if not messagebox.askyesno(
            "确认删除档位",
            f"删除 itemID {self._product_id} 的第 {self._sub_index} 档？",
        ):
            return
        if self.app.shop.remove_sub(self._product_id, self._sub_index):
            audit.log("删除商城档位",
                      f"itemID {self._product_id} 档 {self._sub_index}")
            self._pending_reload = True
            self._sub_index = None
            self._clear_form()
            self.refresh()

    # ---- 商品操作 ----
    def _upsert(self) -> None:
        raw = self.new_id.get().strip()
        if not raw.isdigit():
            messagebox.showerror("输入错误", "itemID 必须是数字")
            return
        pid = int(raw)
        if not self.app.items.get(pid):
            if not messagebox.askyesno(
                "道具不存在",
                f"itemID {pid} 不在 Item.csv 里。\n\n"
                "上架后玩家购买时服务端会返回 BUY_FAIL_SYSTEM_ERROR。\n继续？",
            ):
                return
        existing = self.app.shop.products.get(pid)
        if existing:
            self.app.shop.set_currency(pid, self.new_currency.get() == "点券")
            msg = f"itemID {pid} 已在商城中，已更新货币类型。"
        else:
            self.app.shop.upsert_product(pid, self.new_currency.get() == "点券", [])
            self.app.shop.add_sub(pid, count=1, duration=30, price=1000)
            msg = f"itemID {pid} 已上架，并创建了 1 个默认档位（1 个/30 天/1000）。"
        audit.log("上架商品", f"itemID {pid} 货币 {self.new_currency.get()}")
        self._pending_reload = True
        self._product_id = pid
        self.refresh()
        messagebox.showinfo("已加入", msg + "\n\n记得保存并重新加载。")

    def _delete(self) -> None:
        if not self._require_product():
            return
        pid = self._product_id
        if not messagebox.askyesno("确认删除", f"从商城移除 itemID {pid}？"):
            return
        self.app.shop.remove_product(pid)
        audit.log("移除商品", f"itemID {pid}")
        self._pending_reload = True
        self._product_id = None
        self._sub_index = None
        self._clear_form()
        self.refresh()

    def _set_currency(self) -> None:
        if not self._require_product():
            return
        self.app.shop.set_currency(self._product_id, self.cur_var.get() == "点券")
        audit.log("切换商品货币", f"itemID {self._product_id} → {self.cur_var.get()}")
        self._pending_reload = True
        self.refresh()

    def _toggle_popular(self) -> None:
        if not self._require_product():
            return
        self.app.shop.toggle_popular(self._product_id)
        self._pending_reload = True
        self.refresh()

    def _toggle_rec(self, page: str) -> None:
        if not self._require_product():
            return
        self.app.shop.toggle_recommended(page, self._product_id)
        self._pending_reload = True
        self.refresh()

    # ---- 保存 / 重载 ----
    def _save(self) -> None:
        ids = set(self.app.items.items.keys())
        problems = self.app.shop.validate(ids)
        if problems:
            messagebox.showerror("校验失败",
                                 "Shop.json 未保存，存在以下问题：\n\n"
                                 + "\n".join("· " + p for p in problems[:15]))
            return
        try:
            backup = self.app.shop.save(self.app.paths.backups_dir, ids)
        except Exception as e:
            messagebox.showerror("保存失败", str(e))
            return
        audit.log("保存 Shop.json", f"备份 {backup.name if backup else '无'}")
        self._pending_reload = True
        self._update_hint()
        messagebox.showinfo(
            "已保存",
            "Shop.json 已写入。\n\n"
            "下一步必须点「重新加载商城」，否则在线玩家仍按旧价格购买。",
        )

    def _reload_shop(self) -> None:
        if not self.app.server.running:
            messagebox.showwarning(
                "服务端未运行",
                "服务端未运行，配置会在下次启动时自动生效。\n\n"
                "若要在线生效，请先在「运行与日志」页启动服务端。",
            )
            return
        if not messagebox.askyesno(
            "确认重载商城",
            "将发送 dbreload（不是 shopreload）。\n\n"
            "· shopreload 不会清空旧列表，每用一次商品就翻一倍，"
            "会让客户端商城出现重复商品和错位价格。\n"
            "· dbreload 会重建全部 Manager，并给在线用户重推商城。\n"
            "· 若 Shop.json 有语法错误，服务端会直接关闭（工具已先行校验）。\n\n继续？",
        ):
            return
        ok, msg = self.app.send_command("dbreload")
        if not ok:
            messagebox.showerror("发送失败", msg)
            return
        self._pending_reload = False
        self._update_hint()
        audit.log("dbreload（商城重载）", "商城已通过 dbreload 热重载")
        messagebox.showinfo(
            "已下发",
            "dbreload 已发送。\n\n请在「运行与日志」页确认出现：\n"
            "  [Shop] Loaded N products\n"
            "其中 N 应与本页商品数一致；若明显变大说明出现过重复加载。",
        )


__all__ = ["ShopTab"]
