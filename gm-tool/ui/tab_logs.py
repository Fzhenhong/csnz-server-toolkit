"""运行与日志页：启停服务端、控制台命令、实时日志、审计记录。

这里也是所有 GM 指令的出口。控制台命令清单来自 src/servercommands.h，
游戏内 /命令 清单来自 CChannelManager（需目标角色 gameMaster=1）。
"""
from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, ttk

from core import audit
from core.serverio import parse_log_line
from . import theme

P = theme.px

# 控制台命令（servercommands.h 注册的全部）
CONSOLE_COMMANDS = [
    ("status", "服务端状态：内存 / 在线数 / uptime"),
    ("users", "在线用户列表"),
    ("kickall", "踢出全部用户"),
    ("shutdown", "优雅关服（先发维护公告）"),
    ("bans", "封禁总览"),
    ("shopreload", "⚠ 坏命令：不会清空旧列表，商品数会翻倍，改用 dbreload"),
    ("dbreload", "重载全部 Manager（先 Shutdown 再 Init，商城正确重载）"),
    ("sendnotice", "sendnotice <文本>：全服弹窗公告"),
    ("giveitem", "giveitem <UID> <itemID> <数量> <天数>"),
    ("giverewardtoall", "giverewardtoall <rewardID>：给所有注册用户发礼包"),
    ("togglegamemaster", "togglegamemaster <UID>：切换 GM 权限"),
    ("ban", "ban <UID> <1显示理由/2静默> <理由> <天数>"),
    ("unban", "unban <UID>"),
    ("hban", "hban <UID>：按 HWID 封禁"),
    ("ipban", "ipban <UID>：按 IP 封禁"),
    ("unhban", "unhban <hwid>"),
    ("unipban", "unipban <ip>"),
    ("sendevent", "sendevent <UID> <eventID>"),
    ("sendevent2", "sendevent2 <UID>：推送武器解禁事件"),
    ("sendinventory", "sendinventory <UID>：重推背包"),
    ("sendpacket", "sendpacket <UID> <文件名>"),
    ("help", "列出全部命令"),
]

# 游戏内 GM 聊天命令（需目标角色 gameMaster=1）
CHAT_COMMANDS = [
    "/help", "/version", "/disconnect", "/getfreeslots", "/additem", "/giveitem",
    "/addallitems", "/removeitem", "/sendnotice", "/addexp", "/status", "/ban",
    "/hban", "/ipban", "/unban", "/getuid", "/tournament", "/givereward",
    "/giverewardtoall", "/addgroom", "/reqsnapshot", "/addwpnreleasechar",
    "/addpoints", "/givepoints", "/setitemstatus", "/setiteminuse",
    "/sendgmnotice", "/weaponrelease", "/bingo",
]


class LogsTab(ttk.Frame):
    def __init__(self, master, app) -> None:
        super().__init__(master, padding=10)
        self.app = app
        self._server = None
        self._build()

    def bind_server(self, server) -> None:
        self._server = server
        server.subscribe(self._on_line)
        for line in server.lines():
            self._on_line(line)

    def _build(self) -> None:
        outer, acts = theme.page(
            self, "运行与日志",
            "启停服务端、下发控制台命令、查看实时输出与工具侧审计记录。")
        theme.button(acts, "启动服务端", "default", self._start).pack(side="right")
        theme.button(acts, "关闭", "danger", self._stop).pack(
            side="right", padx=(0, P(7)))
        theme.button(acts, "清空显示", "ghost", self._clear).pack(
            side="right", padx=(0, P(7)))

        # ---- 控制台 ----
        con = theme.Card(outer, "控制台", padding=0)
        con.pack(fill="both", expand=True, pady=(P(12), 0))
        self.state_label = tk.Label(con.head, text="", font=theme.FONT_S,
                                    fg=theme.FG3, bg=theme.L2)
        self.state_label.pack(side="right", padx=(0, P(12)))

        cmdbar = tk.Frame(con.body, bg=theme.L2)
        cmdbar.pack(fill="x", padx=P(11), pady=P(9))
        tk.Label(cmdbar, text=">_", font=(theme.MONO, 9, "bold"),
                 fg=theme.ACCENT, bg=theme.L2).pack(side="left")
        self.cmd_var = tk.StringVar()
        ent = tk.Entry(cmdbar, textvariable=self.cmd_var, font=theme.FONT_MONO,
                       bg="#0b1017", fg=theme.FG, insertbackground=theme.FG,
                       bd=0, highlightthickness=1,
                       highlightbackground=theme.LINE2, highlightcolor=theme.ACCENT)
        ent.pack(side="left", fill="x", expand=True, padx=(P(8), P(8)), ipady=P(4))
        ent.bind("<Return>", lambda e: self._send())
        self.cmd_pick = ttk.Combobox(
            cmdbar, values=[c for c, _d in CONSOLE_COMMANDS],
            width=12, state="readonly")
        self.cmd_pick.pack(side="left", padx=(0, P(7)))
        self.cmd_pick.bind("<<ComboboxSelected>>", self._pick_command)
        theme.button(cmdbar, "发送", "primary", self._send).pack(side="left")
        self.cmd_hint = tk.Label(con.body, text="", font=theme.FONT_XS,
                                 fg=theme.FG3, bg=theme.L2, anchor="w",
                                 justify="left", wraplength=P(900))
        self.cmd_hint.pack(fill="x", padx=P(11), pady=(0, P(6)))

        self.log = theme.scroll_text(con.body, height=12)
        self.log.pack(fill="both", expand=True, padx=1, pady=(0, 1))

        # ---- 双栏 ----
        low = tk.Frame(outer, bg=theme.L0, height=P(196))
        low.pack(fill="x", pady=(P(12), 0))
        low.pack_propagate(False)
        low.columnconfigure(0, weight=115)
        low.columnconfigure(1, weight=100)
        low.rowconfigure(0, weight=1)

        ref = theme.Card(low, "游戏内 GM 命令", padding=0)
        ref.grid(row=0, column=0, sticky="nsew", padx=(0, P(14)))
        tk.Label(ref.head, text="需 gameMaster=1", font=theme.FONT_S,
                 fg=theme.FG3, bg=theme.L2).pack(side="right", padx=(0, P(12)))
        chips = tk.Frame(ref.body, bg=theme.L2)
        chips.pack(fill="both", expand=True, padx=P(11), pady=P(10))
        for i, cmd in enumerate(CHAT_COMMANDS):
            tk.Label(chips, text=cmd, font=(theme.MONO, 8), fg="#9db4cf",
                     bg="#141b25", padx=P(6), pady=P(2),
                     highlightthickness=1,
                     highlightbackground=theme.LINE).grid(
                row=i // 5, column=i % 5, sticky="w",
                padx=(0, P(5)), pady=(0, P(5)))

        auditc = theme.Card(low, "审计记录", padding=0)
        auditc.grid(row=0, column=1, sticky="nsew")
        tk.Label(auditc.head, text="工具侧", font=theme.FONT_S,
                 fg=theme.FG3, bg=theme.L2).pack(side="right", padx=(0, P(12)))
        self.audit_text = tk.Text(
            auditc.body, font=(theme.MONO, 8), wrap="none",
            bg=theme.LOG_BG, fg=theme.LOG_FG, bd=0, highlightthickness=0,
            padx=P(8), pady=P(6),
        )
        self.audit_text.pack(fill="both", expand=True, padx=1, pady=(0, 1))
        self._refresh_audit()

    # ---- 日志 ----
    def _on_line(self, line: str) -> None:
        _, level, msg = parse_log_line(line)
        tag = ""
        if level in ("ERROR", "FATAL_ERROR"):
            tag = "err"
        elif level == "WARN":
            tag = "warn"
        elif line.startswith(">>"):
            tag = "cmd"
        theme.append_log(self.log, line, tag)

    def poll(self) -> None:
        """由主窗口每秒调用，把日志文件的增量也显示出来。"""
        self.state_label.configure(
            text=f"服务端 PID {self._server.pid}" if (self._server and self._server.running)
            else "服务端未运行"
        )
        for line in self.app.log_tail.poll():
            self._on_line(line)
        self._refresh_audit()

    def _clear(self) -> None:
        self.log.text.delete("1.0", "end")  # type: ignore[attr-defined]

    def _refresh_audit(self) -> None:
        lines = audit.tail(200)
        self.audit_text.configure(state="normal")
        self.audit_text.delete("1.0", "end")
        self.audit_text.insert("1.0", "\n".join(lines))
        self.audit_text.see("end")
        self.audit_text.configure(state="disabled")

    # ---- 操作 ----
    def _start(self) -> None:
        if not self._server:
            return
        ok, msg = self._server.start(self.app.paths.root)
        if ok:
            # 服务端每次启动新建日志文件，必须重新绑定，否则会读到上一次运行的旧日志
            self.app.log_tail.bind_start()
            # 登录器依赖鉴权服务，一并拉起，与其它两个启动入口保持一致
            if not self.app.auth.ready:
                aok, amsg = self.app.auth.start()
                audit.log("启动鉴权服务（随服务端）",
                          amsg if aok else "失败：" + amsg)
            audit.log("启动服务端", msg)
        else:
            messagebox.showerror("启动失败", msg)

    def _stop(self) -> None:
        if not self._server or not self._server.running:
            messagebox.showinfo("提示", "服务端未运行")
            return
        if not messagebox.askyesno(
            "确认关服",
            "将向服务端发送 shutdown：\n\n"
            "· 先给全服弹窗「Server down for maintenance」\n"
            "· 然后优雅关闭所有 Manager\n\n继续？",
        ):
            return
        ok, msg = self._server.stop()
        audit.log("关闭服务端", msg)

    def _pick_command(self, _event=None) -> None:
        text = self.cmd_pick.get()
        self.cmd_var.set(text.split("   —   ")[0])
        hints = dict(CONSOLE_COMMANDS)
        if text in hints:
            self.cmd_hint.configure(text=hints[text])
        self.cmd_pick.set("")

    def _send(self) -> None:
        cmd = self.cmd_var.get().strip()
        if not cmd:
            return
        if not self._server or not self._server.running:
            messagebox.showwarning("服务端未运行", "请先启动服务端。")
            return
        ok, msg = self.app.send_command(cmd)
        if not ok:
            messagebox.showerror("发送失败", msg)
            return
        self.cmd_var.set("")
        # stdout 全缓冲，命令回显要等缓冲区刷出才看得到；
        # 真正的执行结果以 Logs 目录里的文件日志为准。
        self.log.text.insert("end", f">> {cmd}（已下发，结果稍后出现在下方文件日志中）\n", "cmd")  # type: ignore[attr-defined]
        self.log.text.see("end")  # type: ignore[attr-defined]


__all__ = ["LogsTab", "CONSOLE_COMMANDS", "CHAT_COMMANDS"]
