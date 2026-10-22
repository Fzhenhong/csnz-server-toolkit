"""道具发放页：全量检索 + 批量发放。

检索范围覆盖 ID、内部名、中文名、别名、类名、分类名，并标出目标用户是否已持有。
发放前先在内存里虚跑一遍规则，把「堆叠 / 新建 / 延期 / 背包满 / 道具不存在」
逐条算清楚再落库，避免半途失败留下脏数据。

布局：左结果表 155 / 右「目标用户 + 道具详情」100。
"""
from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, ttk

from core import audit
from core.itemdb import CATEGORY_NAMES
from . import theme

P = theme.px


class ItemsTab(tk.Frame):
    def __init__(self, master, app) -> None:
        super().__init__(master, bg=theme.L0)
        self.app = app
        self._results = []
        self._owned: set[int] = set()
        self._target_user = None
        self._pending = None

        self._build()
        self.search()

    # ---- 布局 ----
    def _build(self) -> None:
        outer, acts = theme.page(
            self, "道具发放",
            "全库检索道具，支持内部名 / 中文名 / 别名 / 分类。"
            "发放前会自动虚拟推演堆叠与背包占用。")
        theme.button(acts, "刷新", "ghost", self.search).pack(side="right")

        # 检索条
        bar = tk.Frame(outer, bg=theme.L0)
        bar.pack(fill="x", pady=(P(13), 0))
        self.search_var = tk.StringVar()
        box = theme.search_box(bar, self.search_var, 30)
        box.pack(side="left")
        box.entry.bind("<Return>", lambda e: self.search())
        self.search_var.trace_add("write", lambda *a: self._schedule_search())

        tk.Label(bar, text="分类", font=theme.FONT_S, fg=theme.FG3,
                 bg=theme.L0).pack(side="left", padx=(P(10), P(4)))
        self.cat_var = tk.StringVar(value="全部")
        cats = ["全部"] + [
            f"{k} {v}" for k, v in
            sorted(CATEGORY_NAMES.items(), key=lambda x: int(x[0]))
        ]
        self.cat_box = ttk.Combobox(bar, textvariable=self.cat_var, values=cats,
                                    width=12, state="readonly")
        self.cat_box.pack(side="left")
        self.cat_box.bind("<<ComboboxSelected>>", lambda e: self.search())

        self.stackable_only = tk.BooleanVar(value=False)
        ttk.Checkbutton(bar, text="只看可堆叠", variable=self.stackable_only,
                        style="BarCheck.TCheckbutton",
                        command=self.search).pack(side="left", padx=(P(10), 0))

        self.count_label = tk.Label(bar, text="", font=theme.FONT_S,
                                    fg=theme.FG3, bg=theme.L0)
        self.count_label.pack(side="right")

        # 主体
        body = tk.Frame(outer, bg=theme.L0)
        body.pack(fill="both", expand=True, pady=(P(12), 0))
        body.columnconfigure(0, weight=155)
        body.columnconfigure(1, weight=100)
        body.rowconfigure(0, weight=1)

        left_card = theme.Card(body, padding=0)
        left_card.grid(row=0, column=0, sticky="nsew", padx=(0, P(14)))
        self.table = theme.Table(
            left_card.body,
            [("id", "ID", 58), ("name", "中文名", 168, "w", True),
             ("raw", "内部名", 122), ("cat", "分类", 76),
             ("grade", "品级", 46, "e"), ("flags", "特性", 100),
             ("owned", "持有", 66)],
            height=10, on_select=self._on_select, on_double=self._give_selected,
        )
        self.table.pack(fill="both", expand=True, padx=1, pady=(0, 1))

        # 右列
        rcol = tk.Frame(body, bg=theme.L0)
        rcol.grid(row=0, column=1, sticky="nsew")
        rcol.columnconfigure(0, weight=1)
        rcol.rowconfigure(1, weight=1)

        # 目标用户
        target = theme.Card(rcol, "目标用户", padding=0)
        target.grid(row=0, column=0, sticky="ew")
        tb = tk.Frame(target.body, bg=theme.L2)
        tb.pack(fill="x", padx=P(12), pady=P(11))

        urow = tk.Frame(tb, bg=theme.L2)
        urow.pack(fill="x")
        self.user_var = tk.StringVar()
        ubox = theme.search_box(urow, self.user_var, 14, theme.L2)
        ubox.configure(bg=theme.L3)
        ubox.pack(side="left", fill="x", expand=True)
        ubox.entry.bind("<Return>", lambda e: self._resolve_user())
        theme.button(urow, "选中", "default", self._resolve_user).pack(
            side="left", padx=(P(6), 0))

        self.user_label = tk.Label(tb, text="未选择", font=theme.FONT_S,
                                   fg=theme.FG3, bg=theme.L2, anchor="w",
                                   justify="left", wraplength=P(300))
        self.user_label.pack(fill="x", pady=(P(7), 0))

        nums = tk.Frame(tb, bg=theme.L2)
        nums.pack(fill="x", pady=(P(9), 0))
        nums.columnconfigure(0, weight=1)
        nums.columnconfigure(1, weight=1)
        self.count_var = tk.StringVar(value="1")
        self.days_var = tk.StringVar(value="0")
        for i, (label, var, note) in enumerate((
                ("数量", self.count_var, ""),
                ("天数", self.days_var, "0 = 永久"))):
            cell = tk.Frame(nums, bg=theme.L2)
            cell.grid(row=0, column=i, sticky="ew",
                      padx=(0 if i == 0 else P(8), 0))
            tk.Label(cell, text=f"{label}　{note}", font=theme.FONT_XS,
                     fg=theme.FG3, bg=theme.L2, anchor="w").pack(anchor="w")
            ttk.Entry(cell, textvariable=var, width=8).pack(
                fill="x", pady=(P(3), 0))

        self.give_btn = theme.button(tb, "发放选中道具", "primary",
                                     self._give_selected)
        self.give_btn.pack(fill="x", pady=(P(9), 0))

        # 道具详情
        det = theme.Card(rcol, "道具详情", padding=0)
        det.grid(row=1, column=0, sticky="nsew", pady=(P(14), 0))
        db = tk.Frame(det.body, bg=theme.L2)
        db.pack(fill="both", expand=True, padx=P(12), pady=P(11))

        self.detail = tk.Label(db, text="未选择道具", font=(theme.MONO, 8),
                               fg=theme.FG2, bg=theme.L2, justify="left",
                               anchor="nw")
        self.detail.pack(fill="both", expand=True, anchor="nw")

        alias_row = tk.Frame(db, bg=theme.L2)
        alias_row.pack(fill="x", pady=(P(8), 0))
        tk.Label(alias_row, text="自定义中文名", font=theme.FONT_XS,
                 fg=theme.FG3, bg=theme.L2).pack(side="left")
        self.alias_var = tk.StringVar()
        ttk.Entry(alias_row, textvariable=self.alias_var, width=12).pack(
            side="left", fill="x", expand=True, padx=(P(6), P(6)))
        theme.button(alias_row, "保存", "default", self._save_alias).pack(
            side="right")

    # ---- 检索 ----
    def _schedule_search(self) -> None:
        if self._pending:
            self.after_cancel(self._pending)
        self._pending = self.after(220, self.search)

    def search(self) -> None:
        self._pending = None
        cat = None
        if self.cat_var.get() != "全部":
            cat = int(self.cat_var.get().split(" ", 1)[0])
        needle = self.search_var.get().strip()
        self._results = self.app.items.search(
            needle, category=cat, stackable_only=self.stackable_only.get()
        )
        self._render()
        self.count_label.configure(
            text=f"命中 {len(self._results)} / 全库 {len(self.app.items)}")

    def _render(self) -> None:
        rows, tags = [], []
        for item in self._results:
            flags = []
            if item.stackable:
                flags.append("可堆叠")
            if item.can_extend:
                flags.append("可续期")
            if item.is_costume:
                flags.append("装扮")
            if item.special_note:
                flags.append("特殊")
            owned = item.id in self._owned
            rows.append((item.id, item.display_name, item.name,
                         item.category_name, item.grade, " ".join(flags),
                         "● 已持有" if owned else ""))
            tags.append("owned" if owned else ("warn" if item.special_note else ""))
        self.table.set_rows(rows, tags)

    def _on_select(self) -> None:
        row = self.table.selected_row()
        if not row:
            return
        item = self.app.items.get(int(row[0]))
        if not item:
            return
        lines = [
            f"ID        {item.id}",
            f"内部名    {item.name}",
            f"中文名    {item.cn_name or '（未找到）'}",
            f"类名      {item.class_name}",
            f"分类      {item.category_name}（{item.category}）",
            f"品级      {item.grade}　用途 {item.use_type}",
            f"可堆叠    {'是' if item.stackable else '否'}"
            f"　可续期 {'是' if item.can_extend else '否'}",
        ]
        if item.special_note:
            lines += ["", "⚠ " + item.special_note]
        self.detail.configure(text="\n".join(lines))
        self.alias_var.set(item.alias)

    def _save_alias(self) -> None:
        row = self.table.selected_row()
        if not row:
            messagebox.showinfo("提示", "请先选择一个道具")
            return
        item = self.app.items.get(int(row[0]))
        if not item:
            return
        item.alias = self.alias_var.get().strip()
        self.app.items.save_aliases(self.app.aliases_path)
        audit.log("设置道具别名", f"{item.id} → {item.alias}")
        self._render()

    # ---- 用户 ----
    def _resolve_user(self) -> None:
        user = self.app.db.find_user_by_name(self.user_var.get())
        if not user:
            self.user_label.configure(text="未找到该用户", fg=theme.DANGER)
            self._target_user = None
            self._owned = set()
            self._render()
            return
        self._target_user = user
        self._owned = self.app.db.owned_item_ids(user.user_id)
        state = "在线" if user.online else "离线"
        self.user_label.configure(
            text=f"UID {user.user_id} {user.username}（{user.game_name}）{state}　"
                 f"已持有 {len(self._owned)} 种",
            fg=theme.FG2)
        self._render()

    # ---- 发放 ----
    def _give_selected(self) -> None:
        if not self._target_user:
            if not self.user_var.get().strip():
                messagebox.showinfo("提示", "请先填写目标用户并点「选中」")
                return
            self._resolve_user()
            if not self._target_user:
                return
        selected = self.table.selected_row()
        item = self.app.items.get(int(selected[0])) if selected else None
        if not item:
            messagebox.showinfo("提示", "请先选择一个道具")
            return
        try:
            count = int(self.count_var.get())
            days = int(self.days_var.get())
        except ValueError:
            messagebox.showerror("输入错误", "数量 / 天数必须是整数")
            return
        if count <= 0:
            messagebox.showerror("输入错误", "数量必须 ≥ 1")
            return

        user = self._target_user
        if user.online:
            cmd = f"giveitem {user.user_id} {item.id} {count} {days}"
            if not messagebox.askyesno(
                "用户在线",
                f"{user.game_name} 当前在线，将通过 GM 指令发放：\n\n  {cmd}\n\n继续？",
            ):
                return
            ok, msg = self.app.send_command(cmd)
            if not ok:
                messagebox.showerror("发送失败", msg)
            else:
                audit.log("在线发道具",
                          f"UID {user.user_id} item {item.id} ×{count} {days}天")
                messagebox.showinfo("已发送", "指令已下发，结果见「运行与日志」页")
            return

        self.app.backup_db()
        ok, msg = self.app.db.add_item(user.user_id, item, count, days)
        audit.log("离线发道具",
                  f"UID {user.user_id} item {item.id} ×{count} {days}天 → {msg}")
        if ok:
            self._resolve_user()
            messagebox.showinfo("发放结果", msg)
        else:
            messagebox.showerror("发放失败", msg)


__all__ = ["ItemsTab"]
