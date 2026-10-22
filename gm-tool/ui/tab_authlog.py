"""安全日志页：鉴权服务的登录失败、限频、撞库来源。

这是「限频 + 一键封禁联动」的落地界面：

    IP 汇总（谁失败最多）→ 展开明细 → 一键封 IP / 解除限频

鉴权服务未配置时页面只显示提示，不影响其它功能。
"""
from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, ttk

from core import audit
from core.authclient import AuthAdmin, AuthAdminError
from core.database import minutes_to_str
from . import theme

P = theme.px

KIND_LABELS = {
    "login_ok": "登录成功",
    "login_fail": "登录失败",
    "register_ok": "注册成功",
    "register_fail": "注册失败",
    "rate_blocked": "触发限频",
    "kicked": "会话踢出",
}


class AuthLogTab(ttk.Frame):
    def __init__(self, master, app) -> None:
        super().__init__(master, padding=10)
        self.app = app
        self._ip_rows: list[dict] = []
        self._event_rows: list[dict] = []

        self._build()
        self.after(200, self.refresh)

    # ---- 布局 ----
    def _build(self) -> None:
        outer, acts = theme.page(
            self, "安全日志",
            "鉴权服务的登录失败、限频与撞库来源。按 IP 汇总后可一键联动封禁。")
        theme.button(acts, "服务状态", "ghost", self._health).pack(side="right")
        theme.button(acts, "刷新", "default", self.refresh).pack(
            side="right", padx=(0, P(7)))

        self.stat_label = tk.Label(outer, text="", font=theme.FONT_S,
                                   fg=theme.FG3, bg=theme.L0, anchor="w",
                                   justify="left", wraplength=P(1000))
        self.stat_label.pack(fill="x", pady=(P(9), 0))

        # ---- IP 汇总 ----
        ipc = theme.Card(outer, "按 IP 汇总", padding=0)
        ipc.pack(fill="both", expand=True, pady=(P(10), 0))
        tk.Label(ipc.head, text="失败次数降序", font=theme.FONT_S,
                 fg=theme.FG3, bg=theme.L2).pack(side="left", padx=(P(4), 0))
        tk.Label(ipc.head, text="双击行可筛选该 IP 的明细", font=theme.FONT_XS,
                 fg="#5d6b7d", bg=theme.L2).pack(side="right", padx=(0, P(12)))
        self.ip_table = theme.Table(
            ipc.body,
            [("ip", "IP", 150), ("fails", "失败", 70, "e"),
             ("oks", "成功", 70, "e"), ("total", "总计", 70, "e"),
             ("last", "最近", 140), ("state", "判定", 120, "w", True)],
            height=6, on_double=self._on_ip_double,
        )
        self.ip_table.pack(fill="both", expand=True, padx=1, pady=(0, 1))

        # ---- IP 操作 ----
        ops = tk.Frame(outer, bg=theme.L0)
        ops.pack(fill="x", pady=(P(9), 0))
        theme.button(ops, "封禁选中 IP", "danger", self._ban_ip).pack(side="left")
        theme.button(ops, "解除限频", "default", self._reset_limit).pack(
            side="left", padx=(P(7), 0))
        theme.button(ops, "从黑名单移除", "default", self._unban_ip).pack(
            side="left", padx=(P(7), 0))
        self.hint = tk.Label(ops, text="", font=theme.FONT_XS, fg=theme.FG3,
                             bg=theme.L0)
        self.hint.pack(side="left", padx=(P(10), 0))
        tk.Label(ops, text="自动封禁写入 IPBanList 后永久生效，需手动解封",
                 font=theme.FONT_XS, fg="#5d6b7d", bg=theme.L0).pack(side="right")

        # ---- 事件明细 ----
        ec = theme.Card(outer, "事件明细", padding=0)
        ec.pack(fill="both", expand=True, pady=(P(10), 0))
        self._event_sub = tk.Label(ec.head, text="", font=theme.FONT_S,
                                   fg=theme.FG3, bg=theme.L2)
        self._event_sub.pack(side="right", padx=(0, P(12)))
        self.event_table = theme.Table(
            ec.body,
            [("ts", "时间", 120), ("kind", "类型", 88), ("user", "账号", 116),
             ("ip", "IP", 136), ("uid", "UID", 54, "e"),
             ("detail", "说明", 180, "w", True)],
            height=8,
        )
        self.event_table.pack(fill="both", expand=True, padx=1, pady=(0, 1))

    # ---- 数据 ----
    def _client(self) -> AuthAdmin:
        return AuthAdmin(
            self.app.cfg.get("auth_base_url", ""),
            self.app.cfg.get("auth_api_key", ""),
        )

    def refresh(self) -> None:
        client = self._client()
        if not client.configured:
            self.stat_label.configure(
                text="未配置鉴权服务：请在 config.json 填 auth_base_url 与 auth_api_key",
                fg=theme.WARN)
            return
        try:
            stat = client.stats().get("stats", {})
            self._ip_rows = client.ip_summary(100)
            self._event_rows = client.events(300)
        except AuthAdminError as e:
            self.stat_label.configure(text=f"读取失败：{e}", fg=theme.DANGER)
            return

        self.stat_label.configure(
            fg=theme.FG3,
            text=(f"成功 {stat.get('login_ok', 0)} · 失败 {stat.get('login_fail', 0)}"
                  f" · 限频 {stat.get('rate_blocked', 0)}"
                  f" · 共 {stat.get('total', 0)} 条")
        )

        self.ip_table.set_rows([
            (r["ip"], r["fails"], r["oks"], r["total"], minutes_to_str(r["last_ts"]))
            for r in self._ip_rows
        ], tags=["warn" if r["fails"] >= 5 else "" for r in self._ip_rows])

        self._render_events(self._event_rows)

    def _render_events(self, rows: list[dict]) -> None:
        self.event_table.set_rows([
            (minutes_to_str(r["ts"]), KIND_LABELS.get(r["kind"], r["kind"]),
             r["username"] or "-", r["ip"] or "-",
             r["user_id"] or "-", r["detail"] or "")
            for r in rows
        ], tags=["warn" if r["kind"] in ("login_fail", "rate_blocked") else ""
                 for r in rows])

    def _on_ip_double(self) -> None:
        row = self.ip_table.selected_row()
        if not row:
            return
        ip = row[0]
        client = self._client()
        try:
            rows = client.events(200, ip=str(ip))
        except AuthAdminError as e:
            messagebox.showerror("读取失败", str(e))
            return
        self._render_events(rows)
        self.hint.configure(text=f"已筛选 IP {ip}（{len(rows)} 条）")

    # ---- 操作 ----
    def _selected_ip(self) -> str | None:
        row = self.ip_table.selected_row()
        if not row:
            messagebox.showinfo("提示", "请先在上表选中一个 IP")
            return None
        return str(row[0])

    def _ban_ip(self) -> None:
        ip = self._selected_ip()
        if not ip:
            return
        if not messagebox.askyesno(
            "确认封禁 IP",
            f"把 {ip} 加入 IPBanList？\n\n"
            "· 立即生效：服务端在 TCP 连接建立时就会拒绝该 IP\n"
            "· 也会阻止该 IP 注册新账号\n"
            "· 如果这是网吧共享 IP，可能误伤其他玩家",
        ):
            return
        self.app.backup_db()
        try:
            self.app.db.ban_ip(ip)
        except Exception as e:
            messagebox.showerror("封禁失败", str(e))
            return
        audit.log("封禁 IP", f"{ip}（来自安全日志）")
        # 顺手解除该 IP 的限频，避免误封后管理员自己也被锁
        try:
            self._client().reset_rate_limit(ip=ip)
        except AuthAdminError:
            pass
        messagebox.showinfo("已封禁", f"{ip} 已加入 IP 黑名单")
        self.app.tab_bans.refresh()

    def _unban_ip(self) -> None:
        """解封：自动封禁是永久的，这里提供手动恢复。"""
        ip = self._selected_ip()
        if not ip:
            return
        self.app.backup_db()
        try:
            self.app.db.unban_ip(ip)
        except Exception as e:
            messagebox.showerror("解封失败", str(e))
            return
        try:
            self._client().reset_rate_limit(ip=ip)
        except AuthAdminError:
            pass
        audit.log("解封 IP", f"{ip}（来自安全日志）")
        self.hint.configure(text=f"已从黑名单移除 {ip}")
        self.refresh()
        self.app.tab_bans.refresh()

    def _reset_limit(self) -> None:
        ip = self._selected_ip()
        if not ip:
            return
        try:
            self._client().reset_rate_limit(ip=ip)
        except AuthAdminError as e:
            messagebox.showerror("操作失败", str(e))
            return
        audit.log("解除限频", ip)
        self.hint.configure(text=f"已解除 {ip} 的限频")
        self.refresh()

    def _health(self) -> None:
        client = self._client()
        if not client.configured:
            messagebox.showinfo(
                "未配置",
                "请在 GM_Tool/config.json 填写：\n"
                '  "auth_base_url": "http://你的服务器:8080",\n'
                '  "auth_api_key": "与鉴权服务一致的密钥"',
            )
            return
        try:
            info = client.health()
        except AuthAdminError as e:
            messagebox.showerror("连接失败", str(e))
            return
        messagebox.showinfo(
            "鉴权服务正常",
            f"地址：{client.base_url}\n"
            f"数据库：{'已找到' if info.get('db') else '未找到'}",
        )


__all__ = ["AuthLogTab"]
