"""用户管理页：账号列表、数值修改、背包查看、GM 权限。

在线用户的所有改动都走 GM 指令而不是写库——服务端内存里持有 IUser 对象，
任何在线行为都会用内存值 UpdateCharacter 覆盖数据库。
离线用户才直接写库。

布局：左表格 155 / 右详情 100，详情为「身份 → 数值 → 档案 → 背包 → 操作」。
"""
from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, ttk

from core import audit
from core.database import days_left, minutes_to_str, now_minutes
from . import theme

P = theme.px


class UsersTab(tk.Frame):
    def __init__(self, master, app) -> None:
        super().__init__(master, bg=theme.L0)
        self.app = app
        self._users = []
        self._current = None
        self._inventory = []
        self._dyn: dict[str, tk.Label] = {}

        self._build()
        self.refresh()

    # ---- 布局 ----
    def _build(self) -> None:
        outer = tk.Frame(self, bg=theme.L0)
        outer.pack(fill="both", expand=True, padx=P(18), pady=(P(14), P(14)))

        # 页头
        head = tk.Frame(outer, bg=theme.L0)
        head.pack(fill="x")
        left = tk.Frame(head, bg=theme.L0)
        left.pack(side="left", fill="x", expand=True)
        tk.Label(left, text="用户管理", font=theme.FONT_TITLE, fg=theme.FG,
                 bg=theme.L0, anchor="w").pack(anchor="w")
        tk.Label(left, text="搜索账号、修改数值、查看背包。在线用户的改动通过 GM "
                            "指令下发，离线用户直接写库。",
                 font=theme.FONT_S, fg=theme.FG3, bg=theme.L0,
                 anchor="w").pack(anchor="w", pady=(P(3), 0))
        acts = tk.Frame(head, bg=theme.L0)
        acts.pack(side="right", anchor="n")
        theme.button(acts, "刷新", "ghost", self.refresh).pack(side="right")

        # 工具条
        bar = tk.Frame(outer, bg=theme.L0)
        bar.pack(fill="x", pady=(P(13), 0))
        box = tk.Frame(bar, bg=theme.L3, highlightthickness=1,
                       highlightbackground=theme.LINE2)
        box.pack(side="left")
        theme.icon(box, "search", "#5f6f85", P(13), theme.L3).pack(
            side="left", padx=(P(8), 0))
        self.search_var = tk.StringVar()
        ent = tk.Entry(box, textvariable=self.search_var, font=theme.FONT,
                       bg=theme.L3, fg=theme.FG, insertbackground=theme.FG,
                       bd=0, highlightthickness=0, width=26)
        ent.pack(side="left", padx=(P(6), P(8)), pady=P(5))
        ent.bind("<Return>", lambda e: self.refresh())
        self.search_var.trace_add("write", lambda *a: self.refresh())

        self.only_online = tk.BooleanVar(value=False)
        ttk.Checkbutton(bar, text="只看在线", variable=self.only_online,
                        style="BarCheck.TCheckbutton",
                        command=self.refresh).pack(side="left", padx=(P(10), 0))
        self.only_banned = tk.BooleanVar(value=False)
        ttk.Checkbutton(bar, text="只看封禁", variable=self.only_banned,
                        style="BarCheck.TCheckbutton",
                        command=self.refresh).pack(side="left", padx=(P(10), 0))

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
            [("id", "UID", 50), ("user", "账号", 112), ("name", "昵称", 120, "w", True),
             ("lv", "等级", 48, "e"), ("pts", "点券", 84, "e"),
             ("items", "道具", 50, "e"), ("state", "状态", 72),
             ("ban", "封禁", 108)],
            height=10, on_select=self._on_select,
        )
        self.table.pack(fill="both", expand=True, padx=1, pady=(0, 1))

        # ---- 右详情 ----
        right = theme.Card(body, "账号详情", padding=0)
        right.grid(row=0, column=1, sticky="nsew")
        rb = tk.Frame(right.body, bg=theme.L2)
        rb.pack(fill="both", expand=True, padx=P(14), pady=P(12))

        # 身份
        ident = tk.Frame(rb, bg=theme.L2)
        ident.pack(fill="x")
        self.avatar = tk.Label(ident, text="—", font=(theme.FAMILY, 10, "bold"),
                               fg="#a9c2e0", bg="#2b3a52", width=3,
                               height=1, bd=0, highlightthickness=1,
                               highlightbackground="#33435a")
        self.avatar.pack(side="left")
        nm = tk.Frame(ident, bg=theme.L2)
        nm.pack(side="left", padx=(P(10), 0))
        self.d_name = tk.Label(nm, text="未选择用户", font=theme.FONT_MD,
                               fg=theme.FG, bg=theme.L2, anchor="w")
        self.d_name.pack(anchor="w")
        self.d_sub = tk.Label(nm, text="在左侧列表选择一个账号",
                              font=(theme.MONO, 8), fg=theme.FG3, bg=theme.L2,
                              anchor="w")
        self.d_sub.pack(anchor="w")
        self.d_state = tk.Frame(ident, bg=theme.L2)
        self.d_state.pack(side="right")

        # 数值
        tk.Frame(rb, bg=theme.L2, height=P(12)).pack()
        theme.section(rb, "数值")
        grid = tk.Frame(rb, bg=theme.L2)
        grid.pack(fill="x", pady=(P(7), 0))
        for i in range(3):
            grid.columnconfigure(i, weight=1, uniform="num")
        self.var_points = tk.StringVar()
        self.var_exp = tk.StringVar()
        self.var_level = tk.StringVar()
        for i, (label, var, unit) in enumerate((
                ("点券", self.var_points, "点"),
                ("经验", self.var_exp, "exp"),
                ("等级", self.var_level, "级"))):
            cell = tk.Frame(grid, bg=theme.L2)
            cell.grid(row=0, column=i, sticky="ew",
                      padx=(0 if i == 0 else P(8), 0))
            tk.Label(cell, text=label, font=theme.FONT_XS, fg=theme.FG3,
                     bg=theme.L2, anchor="w").pack(anchor="w")
            row = tk.Frame(cell, bg=theme.L2)
            row.pack(fill="x", pady=(P(3), 0))
            ttk.Entry(row, textvariable=var, width=8).pack(side="left",
                                                           fill="x", expand=True)
            tk.Label(row, text=unit, font=theme.FONT_XS, fg=theme.FG3,
                     bg=theme.L2).pack(side="left", padx=(P(4), 0))

        btns = tk.Frame(rb, bg=theme.L2)
        btns.pack(fill="x", pady=(P(7), 0))
        theme.button(btns, "按输入覆盖", "primary", self._apply_values).pack(
            side="left", fill="x", expand=True)
        theme.button(btns, "＋1 万", "default",
                     lambda: self._quick_points(10000)).pack(side="left",
                                                             padx=(P(6), 0))
        theme.button(btns, "−1 万", "default",
                     lambda: self._quick_points(-10000)).pack(side="left",
                                                              padx=(P(6), 0))
        self.num_hint = tk.Label(rb, text="", font=theme.FONT_XS, fg="#66748a",
                                 bg=theme.L2, anchor="w", justify="left",
                                 wraplength=P(330))
        self.num_hint.pack(fill="x", pady=(P(6), 0))

        # 档案
        tk.Frame(rb, bg=theme.L2, height=P(10)).pack()
        theme.section(rb, "档案")
        kv = tk.Frame(rb, bg=theme.L2)
        kv.pack(fill="x", pady=(P(6), 0))
        for i in range(2):
            kv.columnconfigure(i, weight=1, uniform="kv")
        for i, (key, label) in enumerate((
                ("cash", "现金"), ("honor", "荣誉 / 里程"),
                ("battle", "战绩"), ("kd", "击杀 / 死亡"),
                ("clan", "公会"), ("reg", "注册"),
                ("last", "最后登录"), ("ip", "最后 IP"))):
            cell = tk.Frame(kv, bg=theme.L2)
            cell.grid(row=i // 2, column=i % 2, sticky="ew",
                      padx=(0 if i % 2 == 0 else P(16), 0), pady=P(2))
            tk.Label(cell, text=label, font=theme.FONT_XS, fg=theme.FG3,
                     bg=theme.L2, anchor="w", width=9).pack(side="left")
            val = tk.Label(cell, text="—", font=(theme.MONO, 8), fg=theme.FG,
                           bg=theme.L2, anchor="w")
            val.pack(side="left", padx=(P(4), 0))
            self._dyn[key] = val

        # 背包
        tk.Frame(rb, bg=theme.L2, height=P(10)).pack()
        inv_head = tk.Frame(rb, bg=theme.L2)
        inv_head.pack(fill="x")
        tk.Label(inv_head, text="背包", font=theme.FONT_XS, fg="#61718a",
                 bg=theme.L2).pack(side="left")
        self.inv_label = tk.Label(inv_head, text="", font=(theme.MONO, 8),
                                  fg=theme.FG3, bg=theme.L2)
        self.inv_label.pack(side="right")
        tk.Frame(rb, bg=theme.LINE, height=1).pack(fill="x", pady=(P(4), 0))

        # 底栏：先 pack 到底部，背包再占剩余高度
        foot = tk.Frame(rb, bg=theme.L2)
        foot.pack(side="bottom", fill="x", pady=(P(10), 0))
        self.gm_btn = theme.button(foot, "切换 GM", "default", self._toggle_gm)
        self.gm_btn.pack(side="right", fill="x", expand=True, padx=(P(6), 0))
        theme.button(foot, "封禁", "danger", self._quick_ban).pack(
            side="right", fill="x", expand=True)

        inv_box = tk.Frame(rb, bg=theme.L2, highlightthickness=1,
                           highlightbackground=theme.LINE)
        inv_box.pack(fill="both", expand=True, pady=(P(6), 0))
        self.inv_table = theme.Table(
            inv_box,
            [("slot", "槽", 36), ("item", "道具", 160, "w", True),
             ("count", "数", 40, "e"), ("exp", "到期", 66)],
            height=4, on_double=self._clear_slot, zebra=False,
        )
        self.inv_table.pack(fill="both", expand=True)

        self._render_detail(None)

    # ---- 数据 ----
    def refresh(self) -> None:
        try:
            self._users = self.app.db.list_users()
        except Exception as e:
            messagebox.showerror("读取用户失败", str(e))
            return

        needle = self.search_var.get().strip().lower()
        rows, tags = [], []
        for u in self._users:
            if self.only_online.get() and not u.online:
                continue
            if needle and not (
                needle in u.username.lower()
                or needle in u.game_name.lower()
                or needle == str(u.user_id)
            ):
                continue
            if self.only_banned.get() and not u.banned:
                continue
            state = "● 在线" if u.online else "· 离线"
            name = u.game_name + ("　GM" if u.gm else "")
            rows.append((
                u.user_id, u.username, name, u.level, f"{u.points:,}",
                u.item_count, state, self._ban_text(u),
            ))
            tags.append("banned" if u.banned else ("online" if u.online else ""))

        self.table.set_rows(rows, tags)
        online = sum(1 for u in self._users if u.online)
        banned = sum(1 for u in self._users if u.banned)
        self.count_label.configure(
            text=(f"共 {len(self._users)} · 在线 {online} · "
                  f"封禁 {banned} · 显示 {len(rows)}")
        )
        current_id = self._current.user_id if self._current else None
        self._current = next(
            (u for u in self._users if u.user_id == current_id), None)
        self._render_detail(self._current)

    def _ban_text(self, u) -> str:
        if not u.banned:
            return ""
        label = "封禁" if u.ban_type == 1 else "静默"
        remaining = self._ban_remaining(u.ban_term)
        return f"{label}·{remaining}" if remaining else label

    @staticmethod
    def _ban_remaining(term: int) -> str:
        if not term:
            return "永久"
        left = term - now_minutes()
        if left <= 0:
            return "已过期"
        days = left / 1440
        if days >= 1:
            return f"剩{int(days)}天"
        hours = left / 60
        return f"剩{max(1, int(hours))}小时"

    def _on_select(self) -> None:
        row = self.table.selected_row()
        if not row:
            return
        uid = int(row[0])
        self._current = next((u for u in self._users if u.user_id == uid), None)
        self._render_detail(self._current)

    def _render_detail(self, user) -> None:
        for w in self.d_state.winfo_children():
            w.destroy()
        if user is None:
            self.avatar.configure(text="—")
            self.d_name.configure(text="未选择用户")
            self.d_sub.configure(text="在左侧列表选择一个账号")
            theme.pill(self.d_state, "—", "muted").pack()
            self.num_hint.configure(text="")
            for lb in self._dyn.values():
                lb.configure(text="—")
            self.inv_table.set_rows([])
            self.inv_label.configure(text="")
            return

        self.avatar.configure(text=(user.game_name or user.username)[:1])
        self.d_name.configure(text=user.game_name or user.username)
        self.d_sub.configure(text=f"UID {user.user_id} · {user.username}")
        theme.pill(self.d_state, "在线" if user.online else "离线",
                   "ok" if user.online else "muted").pack()

        self.var_points.set(str(user.points))
        self.var_exp.set(str(user.exp))
        self.var_level.set(str(user.level))
        self.num_hint.configure(
            text=("该用户在线，改动会以 givepoints / addexp 指令下发，不直写数据库。"
                  if user.online else
                  "该用户离线，数值会直接写入数据库，下次登录生效。"))

        self._dyn["cash"].configure(text=f"{user.cash:,}")
        self._dyn["honor"].configure(text=f"{user.honor:,} / {user.mileage:,}")
        self._dyn["battle"].configure(text=f"{user.battles} 场")
        self._dyn["kd"].configure(text=f"{user.kills} / {user.deaths}")
        self._dyn["clan"].configure(text=str(user.clan_id or "—"))
        self._dyn["reg"].configure(text=minutes_to_str(user.register, "—")[-11:])
        self._dyn["last"].configure(text=minutes_to_str(user.last_login, "—")[-11:])
        self._dyn["ip"].configure(text=user.last_ip or "—")

        self._inventory = self.app.db.inventory(user.user_id)
        rows = []
        for r in self._inventory:
            if not r.item_id:
                continue
            item = self.app.items.get(r.item_id)
            name = item.display_name if item else str(r.item_id)
            rows.append((r.slot, name, r.count, days_left(r.expiry)))
        self.inv_table.set_rows(rows)
        self.inv_label.configure(
            text=f"{len(rows)} 件 / 上限 {self._slot_max()}")

    def _slot_max(self) -> int:
        try:
            return self.app.server_config.get("InventorySlotMax", 4000)
        except Exception:
            return 4000

    # ---- 操作 ----
    def _require_user(self):
        if not self._current:
            messagebox.showinfo("提示", "请先在左侧选择一个用户")
            return None
        return self._current

    def _apply_values(self) -> None:
        user = self._require_user()
        if not user:
            return
        try:
            points = int(self.var_points.get())
            exp = int(self.var_exp.get())
            level = int(self.var_level.get())
        except ValueError:
            messagebox.showerror("输入错误", "点券 / 经验 / 等级必须是整数")
            return

        if user.online:
            messagebox.showwarning(
                "用户在线",
                "该用户当前在线。直接改库会被服务端内存中的旧值覆盖。\n\n"
                "请在「运行与日志」页发送 GM 指令，例如：\n"
                f"  givepoints {user.user_id} <增量>\n"
                f"  addexp {user.user_id} <增量>",
            )
            return

        self.app.backup_db()
        try:
            self.app.db.set_character_fields(
                user.user_id, points=points, exp=exp, level=level
            )
        except Exception as e:
            messagebox.showerror("写入失败", str(e))
            return
        audit.log("修改数值", f"UID {user.user_id} 点券={points} 经验={exp} 等级={level}")
        self.refresh()
        messagebox.showinfo("完成", "已写入数据库，用户下次登录生效")

    def _quick_points(self, delta: int) -> None:
        user = self._require_user()
        if not user:
            return
        if user.online:
            ok, msg = self.app.send_command(f"givepoints {user.user_id} {delta}")
            if not ok:
                messagebox.showerror("发送失败", msg)
                return
            audit.log("在线加点券", f"UID {user.user_id} 增量 {delta}")
            messagebox.showinfo("已发送", "GM 指令已下发，结果见「运行与日志」页")
            return
        self.app.backup_db()
        new_val = self.app.db.adjust_points(user.user_id, delta)
        audit.log("调整点券", f"UID {user.user_id} 增量 {delta} → {new_val}")
        self.refresh()

    def _toggle_gm(self) -> None:
        user = self._require_user()
        if not user:
            return
        if user.online:
            ok, msg = self.app.send_command(f"togglegamemaster {user.user_id}")
            if not ok:
                messagebox.showerror("发送失败", msg)
                return
            messagebox.showinfo("已发送", "GM 指令已下发")
            return
        self.app.backup_db()
        new_state = not bool(user.gm)
        self.app.db.set_gamemaster(user.user_id, new_state)
        audit.log("切换 GM", f"UID {user.user_id} → {new_state}")
        self.refresh()
        messagebox.showinfo("完成", f"GM 权限已{'开启' if new_state else '关闭'}")

    def _quick_ban(self) -> None:
        user = self._require_user()
        if not user:
            return
        self.app.show("bans")
        try:
            self.app.tab_bans.target_var.set(str(user.user_id))
        except Exception:
            pass

    def _clear_slot(self) -> None:
        user = self._require_user()
        if not user:
            return
        row = self.inv_table.selected_row()
        if not row:
            return
        slot = int(row[0])
        if not messagebox.askyesno(
            "确认清空",
            f"清空 UID {user.user_id} 的第 {slot} 槽？\n\n{row[1]}\n\n"
            "服务端用 itemID=0 的空行占位，不会删除记录。",
        ):
            return
        self.app.backup_db()
        ok, msg = self.app.db.remove_slot(user.user_id, slot)
        if ok:
            audit.log("清空背包槽", f"UID {user.user_id} 槽 {slot}：{row[1]}")
            self.refresh()
        else:
            messagebox.showerror("失败", msg)


__all__ = ["UsersTab"]
