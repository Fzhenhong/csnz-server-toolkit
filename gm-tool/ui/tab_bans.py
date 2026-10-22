"""封禁管理页：账号 / IP / HWID 三条通道。

服务端有三种封禁粒度，实际运营几乎总是要一起封（否则换个号就回来了），
所以这里提供「一键三封」。在线用户封禁后必须踢下线——只是在库里写行，
内存里的 IUser 还在跑，要等下次登录才生效。
"""
from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, ttk

from core import audit
from core.database import minutes_to_str
from . import theme

P = theme.px

BAN_TYPES = {"显示理由（客户端可见）": 1, "静默封禁": 2}


class BansTab(ttk.Frame):
    def __init__(self, master, app) -> None:
        super().__init__(master, padding=10)
        self.app = app
        self._banned_users = []

        self._build()
        self.refresh()

    def _build(self) -> None:
        outer, acts = theme.page(
            self, "封禁管理",
            "账号 / IP / HWID 三条通道。「一键三封」会同时写入三者，"
            "避免换号重进。在线用户封禁后需手动踢下线。")
        theme.button(acts, "刷新", "ghost", self.refresh).pack(side="right")

        # ---- 新建封禁 ----
        form = theme.Card(outer, "新建封禁", padding=0)
        form.pack(fill="x", pady=(P(12), 0))
        tk.Label(form.head, text="写库前自动备份", font=theme.FONT_S,
                 fg=theme.FG3, bg=theme.L2).pack(side="right", padx=(0, P(12)))

        fb = tk.Frame(form.body, bg=theme.L2)
        fb.pack(fill="x", padx=P(13), pady=P(12))
        grid = tk.Frame(fb, bg=theme.L2)
        grid.pack(fill="x")
        grid.columnconfigure(0, weight=115)
        grid.columnconfigure(1, weight=100)
        grid.columnconfigure(2, weight=0, minsize=P(78))
        grid.columnconfigure(3, weight=200)

        def cell(col, text):
            c = tk.Frame(grid, bg=theme.L2)
            c.grid(row=0, column=col, sticky="ew",
                   padx=(0 if col == 0 else P(10), 0))
            tk.Label(c, text=text, font=theme.FONT_XS, fg=theme.FG3,
                     bg=theme.L2, anchor="w").pack(anchor="w")
            return c

        c0 = cell(0, "目标账号")
        self.target_var = tk.StringVar()
        box = theme.search_box(c0, self.target_var, 14, theme.L2)
        box.pack(fill="x", pady=(P(3), 0))
        box.entry.bind("<Return>", lambda e: self._ban_account())

        c1 = cell(1, "封禁方式")
        self.type_var = tk.StringVar(value="显示理由（客户端可见）")
        ttk.Combobox(c1, textvariable=self.type_var, values=list(BAN_TYPES),
                     state="readonly").pack(fill="x", pady=(P(3), 0))

        c2 = cell(2, "天数　0 = 永久")
        self.days_var = tk.StringVar(value="7")
        ttk.Spinbox(c2, from_=0, to=3650, textvariable=self.days_var).pack(
            fill="x", pady=(P(3), 0))

        c3 = cell(3, "理由")
        self.reason_var = tk.StringVar()
        ttk.Entry(c3, textvariable=self.reason_var).pack(fill="x", pady=(P(3), 0))

        brow = tk.Frame(fb, bg=theme.L2)
        brow.pack(fill="x", pady=(P(10), 0))
        theme.button(brow, "一键三封（账号 + IP + HWID）", "danger-solid",
                     self._ban_all).pack(side="left")
        theme.button(brow, "仅封账号", "default", self._ban_account).pack(
            side="left", padx=(P(7), 0))
        theme.button(brow, "解除封禁", "default", self._unban_all).pack(
            side="left", padx=(P(7), 0))
        tk.Label(brow, text="双击列表行可直接解封", font=theme.FONT_XS,
                 fg=theme.FG3, bg=theme.L2).pack(side="right")

        # ---- 封禁列表 ----
        tc = theme.Card(outer, "生效中的封禁", padding=0)
        tc.pack(fill="both", expand=True, pady=(P(12), 0))
        self._ban_count_label = tk.Label(tc.head, text="", font=theme.FONT_S,
                                         fg=theme.FG3, bg=theme.L2)
        self._ban_count_label.pack(side="right", padx=(0, P(12)))
        self.table = theme.Table(
            tc.body,
            [("uid", "UID", 52), ("user", "账号", 110), ("name", "昵称", 100),
             ("type", "类型", 92), ("reason", "理由", 260, "w", True),
             ("term", "到期", 124), ("state", "状态", 74)],
            height=5, on_double=self._unban_selected,
        )
        self.table.pack(fill="both", expand=True, padx=1, pady=(0, 1))

        # ---- IP / HWID ----
        lists = tk.Frame(outer, bg=theme.L0)
        lists.pack(fill="both", expand=True, pady=(P(12), 0))
        lists.columnconfigure(0, weight=1)
        lists.columnconfigure(1, weight=1)
        lists.rowconfigure(0, weight=1)

        ipc = theme.Card(lists, "IP 黑名单", padding=0)
        ipc.grid(row=0, column=0, sticky="nsew", padx=(0, P(14)))
        self._ip_count = tk.Label(ipc.head, text="", font=theme.FONT_S,
                                  fg=theme.FG3, bg=theme.L2)
        self._ip_count.pack(side="right", padx=(0, P(12)))
        theme.button(ipc.head, "移除选中", "ghost", self._remove_ip).pack(
            side="right", padx=(0, P(6)))
        self.ip_list = tk.Listbox(
            ipc.body, font=(theme.MONO, 8), bg="#0c1118", fg=theme.FG2,
            selectbackground=theme.ACCENT_BG, selectforeground="#cfe0ff",
            bd=0, highlightthickness=0, activestyle="none",
            relief="flat",
        )
        self.ip_list.pack(fill="both", expand=True, padx=1, pady=(0, 1))

        hc = theme.Card(lists, "HWID 黑名单", padding=0)
        hc.grid(row=0, column=1, sticky="nsew")
        self._hwid_count = tk.Label(hc.head, text="", font=theme.FONT_S,
                                    fg=theme.FG3, bg=theme.L2)
        self._hwid_count.pack(side="right", padx=(0, P(12)))
        theme.button(hc.head, "移除选中", "ghost", self._remove_hwid).pack(
            side="right", padx=(0, P(6)))
        self.hwid_list = tk.Listbox(
            hc.body, font=(theme.MONO, 8), bg="#0c1118", fg=theme.FG2,
            selectbackground=theme.ACCENT_BG, selectforeground="#cfe0ff",
            bd=0, highlightthickness=0, activestyle="none",
            relief="flat",
        )
        self.hwid_list.pack(fill="both", expand=True, padx=1, pady=(0, 1))

    # ---- 列表 ----
    def refresh(self) -> None:
        users = {u.user_id: u for u in self.app.db.list_users()}
        rows = []
        self._banned_users = []
        for uid, u in users.items():
            # u.banned 已在数据层统一判定（过期不算封禁中）
            if not u.banned:
                continue
            rows.append((
                uid, u.username, u.game_name,
                "显示理由" if u.ban_type == 1 else "静默",
                u.ban_reason,
                minutes_to_str(u.ban_term) if u.ban_term else "永久",
                "生效中",
            ))
            self._banned_users.append(uid)
        self.table.set_rows(rows)

        ips, hwids = self.app.db.ban_lists()
        self.ip_list.delete(0, "end")
        for ip in ips:
            self.ip_list.insert("end", ip)
        self.hwid_list.delete(0, "end")
        for h in hwids:
            self.hwid_list.insert("end", h.hex())

    def _resolve(self):
        name = self.target_var.get().strip()
        if not name:
            messagebox.showinfo("提示", "请填写 UID / 账号 / 昵称")
            return None
        user = self.app.db.find_user_by_name(name)
        if not user:
            messagebox.showerror("未找到", f"找不到用户：{name}")
        return user

    def _params(self, user) -> tuple[int, str, int]:
        ban_type = BAN_TYPES.get(self.type_var.get(), 1)
        reason = self.reason_var.get().strip() or "违反服务器规则"
        try:
            days = int(self.days_var.get())
        except ValueError:
            days = 7
        if days == 0:
            days = 36500  # 服务端 term=0 会被当成 999999 分钟，这里显式给 100 年
        return ban_type, reason, days

    # ---- 封禁 ----
    def _ban_account(self) -> None:
        user = self._resolve()
        if not user:
            return
        ban_type, reason, days = self._params(user)
        self.app.backup_db()
        self.app.db.ban_user(user.user_id, ban_type, reason, days)
        audit.log("封禁账号", f"UID {user.user_id} {days}天 理由={reason}")
        self._kick(user)
        self.refresh()
        messagebox.showinfo("已封禁", f"{user.game_name} 账号已封 {days} 天")

    def _ban_all(self) -> None:
        user = self._resolve()
        if not user:
            return
        ban_type, reason, days = self._params(user)
        hwid = self.app.db.user_hwid(user.user_id)
        self.app.backup_db()
        self.app.db.ban_user(user.user_id, ban_type, reason, days)
        if user.last_ip:
            self.app.db.ban_ip(user.last_ip)
        if hwid:
            self.app.db.ban_hwid(hwid)
        audit.log(
            "一键三封",
            f"UID {user.user_id} {days}天 IP={user.last_ip} HWID={hwid.hex() if hwid else '-'}",
        )
        self._kick(user)
        self.refresh()
        messagebox.showinfo(
            "已三封",
            f"{user.game_name}\n\n账号：{days} 天\nIP：{user.last_ip or '无'}\n"
            f"HWID：{hwid.hex() if hwid else '无'}",
        )

    def _unban_all(self) -> None:
        user = self._resolve()
        if not user:
            return
        hwid = self.app.db.user_hwid(user.user_id)
        if not messagebox.askyesno(
            "确认解封",
            f"解封 {user.game_name}？\n\n账号、IP、HWID 三条通道都会解除。",
        ):
            return
        self.app.backup_db()
        self.app.db.ban_user(user.user_id, 0, "", 0)
        if user.last_ip:
            self.app.db.unban_ip(user.last_ip)
        if hwid:
            self.app.db.unban_hwid(hwid)
        audit.log("解除封禁", f"UID {user.user_id}")
        self.refresh()
        messagebox.showinfo("已解封", f"{user.game_name} 已解封")

    def _unban_selected(self) -> None:
        row = self.table.selected_row()
        if not row:
            return
        self.target_var.set(str(row[0]))
        self._unban_all()

    def _kick(self, user) -> None:
        """在线用户封禁后必须踢下线，否则内存里的会话还在。"""
        if not user.online:
            return
        if self.app.server.running:
            messagebox.showwarning(
                "需要手动踢下线",
                "该用户当前在线。账号已封，但服务端内存中的会话仍然存在。\n\n"
                "控制台命令没有单用户踢人，请让该用户重新登录，"
                "或在服务端 GUI 的 Session 页踢出。",
            )
        else:
            messagebox.showwarning(
                "用户在线",
                "该用户显示为在线，但服务端不在本工具的管理下，"
                "封禁会在其下次登录时生效。",
            )

    # ---- IP / HWID ----
    def _remove_ip(self) -> None:
        sel = self.ip_list.curselection()
        if not sel:
            return
        ip = self.ip_list.get(sel[0])
        self.app.backup_db()
        self.app.db.unban_ip(ip)
        audit.log("移除 IP 黑名单", ip)
        self.refresh()

    def _remove_hwid(self) -> None:
        sel = self.hwid_list.curselection()
        if not sel:
            return
        hexval = self.hwid_list.get(sel[0])
        self.app.backup_db()
        self.app.db.unban_hwid(bytes.fromhex(hexval))
        audit.log("移除 HWID 黑名单", hexval)
        self.refresh()


__all__ = ["BansTab"]
