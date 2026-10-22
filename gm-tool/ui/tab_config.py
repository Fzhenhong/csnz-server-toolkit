"""服务器配置页：受控编辑 ServerConfig.json。

不做整文件自由编辑：把 Port 改成非数字之类会导致 CServerConfig::Load 失败、
服务端起不来。只暴露白名单字段 + Metadata 开关。

网络配置分两块，含义不同：
· 服务端监听端口（ServerConfig.Port）—— 服务端 bind 的端口；
  监听地址写死在代码里（getaddrinfo 传 NULL + AI_PASSIVE，即 0.0.0.0），
  所以这里只能改端口，没有「绑定 IP」可填。
· 客户端连接地址（launcher.ini）—— 玩家要连的 IP/端口，这才是发给玩家的东西。

布局注意：每个字段的输入控件必须创建在自己的 holder 容器里。
tkinter 按控件的真实父容器布局，若用 ttk.Entry(basic, ...) 创建却把 .grid()
调用在 holder 上，控件会跑到 basic 里，与标签重叠——这正是早期版本的错位原因。
"""


from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, ttk

from core import audit
from core.config import EDITABLE, METADATA_LABELS
from core.launcher_ini import LauncherIni, local_ipv4_addresses
from . import theme

P = theme.px


class ConfigTab(ttk.Frame):
    """全部内容一屏显示：不做页面级滚动。

    上半是网络配置（含启动/关闭与自动重启），下半是基础设置与元数据开关。
    """

    def __init__(self, master, app) -> None:
        super().__init__(master, padding=10)
        self.app = app
        self._vars: dict[str, tk.Variable] = {}
        self._meta_vars: dict[str, tk.BooleanVar] = {}
        self.ini = LauncherIni(self.app.paths.launcher_ini)

        self._build()
        self.load()

    # ---- 布局 ----
    def _build(self) -> None:
        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)
        scroll_outer, scroll_inner = theme.scroll_area(self, theme.L0)
        scroll_outer.grid(row=0, column=0, sticky="nsew")

        body = tk.Frame(scroll_inner, bg=theme.L0)
        body.pack(fill="both", expand=True, padx=P(18), pady=(P(14), P(14)))

        # 页头
        head = tk.Frame(body, bg=theme.L0)
        head.pack(fill="x")
        left = tk.Frame(head, bg=theme.L0)
        left.pack(side="left", fill="x", expand=True)
        tk.Label(left, text="服务器配置", font=theme.FONT_TITLE, fg=theme.FG,
                 bg=theme.L0, anchor="w").pack(anchor="w")
        tk.Label(left, text="受控编辑 ServerConfig.json 与 launcher.ini。"
                            "保存时会校验端口与上下文依赖，不合法不会落盘。",
                 font=theme.FONT_S, fg=theme.FG3, bg=theme.L0,
                 anchor="w").pack(anchor="w", pady=(P(3), 0))
        hacts = tk.Frame(head, bg=theme.L0)
        hacts.pack(side="right", anchor="n")
        theme.button(hacts, "保存配置", "primary", self.save).pack(side="right")
        theme.button(hacts, "重新读取", "ghost", self.load).pack(
            side="right", padx=(0, P(7)))
        self.run_state = tk.Label(hacts, text="", font=theme.FONT_S_B,
                                  fg=theme.FG3, bg=theme.L0)
        self.run_state.pack(side="right", padx=(0, P(12)))

        grid = tk.Frame(body, bg=theme.L0)
        grid.pack(fill="both", expand=True, pady=(P(12), 0))
        grid.columnconfigure(0, weight=1, uniform="cfg")
        grid.columnconfigure(1, weight=1, uniform="cfg")

        # ---- 网络与运行 ----
        net = theme.Card(grid, "网络与运行", padding=0)
        net.grid(row=0, column=0, sticky="nsew", padx=(0, P(14)))
        self.guard_label = theme.pill(net.head, "未开启", "muted")
        self.guard_label.pack(side="right", padx=(0, P(12)))

        nb = tk.Frame(net.body, bg=theme.L2)
        nb.pack(fill="both", expand=True, padx=P(13), pady=P(12))

        self.srv_port = tk.StringVar()
        self.cli_ip = tk.StringVar()
        self._row(nb, "服务端端口", 0)
        ttk.Entry(nb, textvariable=self.srv_port, width=9,
                  font=theme.FONT_MONO).grid(row=0, column=1, sticky="w",
                                             pady=P(3))
        tk.Label(nb, text="TCP + UDP 共用", font=theme.FONT_XS, fg=theme.FG3,
                 bg=theme.L2).grid(row=0, column=2, sticky="w", padx=(P(7), 0))

        self._row(nb, "客户端地址", 1)
        ip_box = ttk.Combobox(nb, textvariable=self.cli_ip, width=15,
                              values=local_ipv4_addresses())
        ip_box.grid(row=1, column=1, sticky="w", pady=P(3))
        tk.Label(nb, text="写入 launcher.ini", font=theme.FONT_XS,
                 fg=theme.FG3, bg=theme.L2).grid(row=1, column=2, sticky="w",
                                                 padx=(P(7), 0))

        self._row(nb, "守护重启", 2)
        self.restart_delay = tk.StringVar(value="5")
        dbox = tk.Frame(nb, bg=theme.L2)
        dbox.grid(row=2, column=1, columnspan=2, sticky="w", pady=P(3))
        ttk.Spinbox(dbox, from_=1, to=300, textvariable=self.restart_delay,
                    width=5, command=self._apply_delay).pack(side="left")
        tk.Label(dbox, text="秒后自动拉起", font=theme.FONT_XS, fg=theme.FG3,
                 bg=theme.L2).pack(side="left", padx=(P(6), 0))

        tk.Label(nb, text="监听地址固定 0.0.0.0 不可改；端口改动需重启服务端。",
                 font=theme.FONT_XS, fg="#66748a", bg=theme.L2, anchor="w",
                 justify="left", wraplength=P(300)).grid(
            row=3, column=1, columnspan=2, sticky="w", pady=(P(4), 0))

        ops = tk.Frame(nb, bg=theme.L2)
        ops.grid(row=4, column=0, columnspan=3, sticky="w", pady=(P(10), 0))
        self.start_btn = theme.button(ops, "启动服务端", "primary", self._start_server)
        self.start_btn.pack(side="left")
        self.stop_btn = theme.button(ops, "关闭", "default", self._stop_server)
        self.stop_btn.pack(side="left", padx=(P(6), 0))
        self.kill_btn = theme.button(ops, "强制结束", "danger", self._kill_server)
        self.kill_btn.pack(side="left", padx=(P(6), 0))
        theme.button(ops, "dbreload", "ghost", self._dbreload).pack(side="left",
                                                                    padx=(P(14), 0))

        # ---- 鉴权服务（登录器依赖它，跟服务端一起管）----
        authrow = tk.Frame(nb, bg=theme.L2)
        authrow.grid(row=5, column=0, columnspan=3, sticky="ew", pady=(P(8), 0))
        tk.Label(authrow, text="鉴权服务", font=theme.FONT_XS, fg=theme.FG3,
                 bg=theme.L2, anchor="e", width=9).pack(side="left", padx=(0, P(8)))
        tk.Label(authrow, text="端口", font=theme.FONT_XS, fg=theme.FG3,
                 bg=theme.L2).pack(side="left")
        self.auth_port = tk.StringVar()
        self.auth_port_entry = ttk.Entry(authrow, textvariable=self.auth_port,
                                         width=7)
        self.auth_port_entry.pack(side="left", padx=(P(4), P(6)))
        theme.button(authrow, "应用端口", "ghost",
                     self._apply_auth_port).pack(side="left")

        self.auth_btn = theme.button(authrow, "启动鉴权", "default",
                                     self._start_auth)
        self.auth_btn.pack(side="left", padx=(P(12), 0))
        self.auth_stop_btn = theme.button(authrow, "停止鉴权", "default",
                                          self._stop_auth)
        self.auth_stop_btn.pack(side="left", padx=(P(6), 0))
        self.auth_state = tk.Label(authrow, text="未运行", font=theme.FONT_XS,
                                   fg=theme.DANGER, bg=theme.L2, anchor="w")
        self.auth_state.pack(side="left", padx=(P(10), 0))

        self.auth_hint = tk.Label(
            nb, text="改端口会同步写入 AuthServer/config.json、Launcher/config.json "
                     "与 GM_Tool/config.json，登录器无需手动改。",
            font=theme.FONT_XS, fg="#66748a", bg=theme.L2, anchor="w",
            justify="left", wraplength=P(420))
        self.auth_hint.grid(row=6, column=0, columnspan=3, sticky="w",
                            padx=(P(62), 0), pady=(P(2), 0))
        nb.columnconfigure(2, weight=1)

        # ---- 基础设置 ----
        basic = theme.Card(grid, "基础设置", padding=0)
        basic.grid(row=0, column=1, sticky="nsew")
        tk.Label(basic.head, text="ServerConfig.json", font=theme.FONT_S,
                 fg=theme.FG3, bg=theme.L2).pack(side="right", padx=(0, P(12)))
        bb = tk.Frame(basic.body, bg=theme.L2)
        bb.pack(fill="both", expand=True, padx=P(13), pady=P(12))
        bb.columnconfigure(1, weight=1, minsize=P(150))
        bb.columnconfigure(3, weight=1, minsize=P(150))

        keys = [k for k in EDITABLE if k != "Port"]
        self._choice_vars: dict[str, tk.StringVar] = {}
        for index, key in enumerate(keys):
            spec = EDITABLE[key]
            label, typ, note = spec[0], spec[1], spec[2]
            choices = spec[3] if len(spec) > 3 else None
            col = 0 if index % 2 == 0 else 2
            row = index // 2
            tk.Label(bb, text=label, font=theme.FONT_XS, fg=theme.FG3,
                     bg=theme.L2, anchor="e", width=10).grid(
                row=row, column=col, sticky="e", pady=P(3),
                padx=(0 if col == 0 else P(14), P(6)))
            if typ is bool:
                var = tk.BooleanVar()
                ttk.Checkbutton(bb, text="启用", variable=var).grid(
                    row=row, column=col + 1, sticky="w", pady=P(3))
                self._vars[key] = var
            elif choices:
                # 枚举字段用下拉框：这些值是固定含义，让用户手填数字必然填错
                var = tk.StringVar()
                wrap = tk.Frame(bb, bg=theme.L2)
                wrap.grid(row=row, column=col + 1, sticky="ew", pady=P(3))
                wrap.columnconfigure(0, weight=1)
                box = ttk.Combobox(
                    wrap, textvariable=var, state="readonly", width=24,
                    values=[f"{k} · {v}" for k, v in choices.items()],
                )
                box.grid(row=0, column=0, sticky="ew")
                if note:
                    tk.Label(wrap, text=note, font=theme.FONT_XS, fg=theme.FG3,
                             bg=theme.L2, anchor="w").grid(
                        row=1, column=0, sticky="w", pady=(P(2), 0))
                self._choice_vars[key] = var
                self._vars[key] = var
            else:
                var = tk.StringVar()
                ttk.Entry(bb, textvariable=var).grid(
                    row=row, column=col + 1, sticky="ew", pady=P(3))
                self._vars[key] = var

        # ---- 元数据 ----
        meta = theme.Card(body, "下发元数据", padding=0)
        meta.pack(fill="x", pady=(P(14), 0))
        tk.Label(meta.head, text=f"决定客户端收到哪些表 · {len(METADATA_LABELS)} 项",
                 font=theme.FONT_S, fg=theme.FG3, bg=theme.L2).pack(
            side="right", padx=(0, P(12)))
        mb = tk.Frame(meta.body, bg=theme.L2)
        mb.pack(fill="x", padx=P(13), pady=P(11))
        MCOLS = 4
        for c in range(MCOLS):
            mb.columnconfigure(c, weight=1, uniform="meta")
        for i, key in enumerate(sorted(METADATA_LABELS)):
            var = tk.BooleanVar()
            self._meta_vars[key] = var
            ttk.Checkbutton(mb, text=METADATA_LABELS[key], variable=var).grid(
                row=i // MCOLS, column=i % MCOLS, sticky="w",
                padx=(0, P(8)), pady=P(2))

        # ---- 底部提示 ----
        tk.Label(body, text="保存会自动备份上一版 ServerConfig.json 与 launcher.ini；"
                            "dbreload 会重建全部 Manager，配置有错会让服务端直接关闭。",
                 font=theme.FONT_XS, fg="#66748a", bg=theme.L0, anchor="w",
                 justify="left", wraplength=P(900)).pack(fill="x", pady=(P(10), 0))

    def _row(self, parent, text: str, row: int) -> None:
        tk.Label(parent, text=text, font=theme.FONT_S, fg=theme.FG2,
                 bg=theme.L2, anchor="e", width=9).grid(
            row=row, column=0, sticky="e", padx=(0, P(8)), pady=P(3))

    # ---- 运行状态 ----
    def _update_run_state(self) -> None:
        sp = self.app.server
        if sp.running:
            text, fg = f"运行中 · PID {sp.pid}", theme.OK
        else:
            text, fg = "未运行", theme.DANGER
        self.run_state.configure(text=text, fg=fg)

        # 守护状态：只要服务端由本工具拉起且没被手动关闭，就一直守护
        if sp.guarding:
            if sp.running:
                self._paint(self.guard_label,
                            f"守护中 {sp.restart_delay:.0f}s", "ok")
            else:
                self._paint(self.guard_label, "等待重启", "warn")
        else:
            self._paint(self.guard_label, "未守护", "muted")

    @staticmethod
    def _paint(lbl, text: str, kind: str) -> None:
        fg, fill, bd = theme.PILL_COLORS[kind]
        lbl.configure(text="● " + text, fg=fg, bg=fill, highlightbackground=bd)

    def _apply_delay(self) -> None:
        try:
            delay = float(self.restart_delay.get())
        except ValueError:
            delay = 5.0
        self.app.server.set_restart_delay(delay)
        self._update_run_state()
        audit.log("守护延迟", f"{delay:.0f}s")

    # ---- 鉴权服务 ----
    def _apply_auth_port(self) -> None:
        """校验并同步鉴权端口到三个配置文件。

        端口值有三个真实消费者，必须一起改，否则登录器连不上：
          AuthServer/config.json  listen_port    服务实际监听
          Launcher/config.json    auth_base_url  登录器连接地址（发给玩家）
          GM_Tool/config.json     auth_base_url  安全日志页读取事件
        """
        raw = self.auth_port.get().strip()
        if not raw.isdigit() or not (1 <= int(raw) <= 65535):
            messagebox.showerror("端口无效", "端口必须是 1-65535 的数字")
            return
        port = int(raw)

        # 与游戏服务端端口相同会直接冲突
        if str(port) == self.srv_port.get().strip():
            messagebox.showerror(
                "端口冲突",
                f"鉴权服务与游戏服务端不能共用端口 {port}，请换一个。")
            return

        running_now = self.app.auth.ready
        if running_now and port != self.app.auth.port:
            if not messagebox.askyesno(
                "需要重启鉴权",
                f"鉴权服务正在运行（{self.app.auth.port}）。\n\n"
                "改端口后需要重启它，期间玩家无法登录。继续？",
            ):
                return

        # 端口是否已被别的程序占用
        from core.authproc import port_open
        if port != self.app.auth.port and port_open("127.0.0.1", port):
            messagebox.showerror(
                "端口被占用",
                f"端口 {port} 已被其他程序占用，请换一个。")
            return

        ok, err = self.app.apply_auth_port(port)
        if not ok:
            messagebox.showerror("保存失败", err)
            return

        audit.log("修改鉴权端口", f"→ {port}")
        self._update_auth_state()
        messagebox.showinfo(
            "已应用",
            f"鉴权端口已设为 {port}，并同步写入：\n"
            "  · AuthServer/config.json\n"
            "  · Launcher/config.json\n"
            "  · GM_Tool/config.json\n\n"
            + ("请点「启动鉴权」重新启动服务。" if not running_now else ""))

    def _start_auth(self) -> None:
        ok, msg = self.app.auth.start()
        if not ok:
            messagebox.showerror("鉴权服务启动失败", msg)
        else:
            audit.log("启动鉴权服务", msg)
        self._update_auth_state()

    def _stop_auth(self) -> None:
        if not self.app.auth.running:
            messagebox.showinfo("提示", "鉴权服务未运行")
            return
        ok, msg = self.app.auth.stop()
        audit.log("停止鉴权服务", msg)
        self._update_auth_state()

    def _update_auth_state(self) -> None:
        """鉴权状态：区分「进程在跑」与「端口可连」，后者才有意义。"""
        a = self.app.auth
        if a.ready:
            text, fg = f"运行中 · {a.host}:{a.port}", theme.OK
        elif a.running:
            text, fg = "启动中…", theme.WARN
        else:
            text, fg = "未运行", theme.DANGER
        try:
            self.auth_state.configure(text=text, fg=fg)
        except Exception:
            pass
        # 按钮可用性：跑起来就不能再启动，没跑就不能停止
        try:
            self.auth_btn.configure(state="disabled" if a.running else "normal")
            self.auth_stop_btn.configure(
                state="normal" if a.running else "disabled")
        except Exception:
            pass

    def _start_server(self) -> None:
        ok, msg = self.app.server.start(self.app.paths.root)
        if not ok:
            messagebox.showerror("启动失败", msg + "\n\n如果是端口占用，"
                                 "请先确认没有另一个服务端实例在运行。")
            return
        self.app.log_tail.bind_start()
        # 一旦由工具拉起，守护即生效，无需额外开关
        # 登录器依赖鉴权服务，跟着服务端一起起来，省得再单独开窗口
        if not self.app.auth.ready:
            aok, amsg = self.app.auth.start()
            audit.log("启动鉴权服务（随服务端）", amsg if aok else "失败：" + amsg)
        self._update_auth_state()

        audit.log("启动服务端", msg)
        self._update_run_state()

    def _stop_server(self) -> None:
        if not self.app.server.running:
            messagebox.showinfo("提示", "服务端未运行")
            return
        if not messagebox.askyesno(
            "确认关闭",
            "将发送 shutdown：先给全服发维护公告，再优雅关闭。\n\n"
            "若开启了自动重启，本次关闭不会触发重启。\n\n继续？",
        ):
            return
        ok, msg = self.app.server.stop()
        audit.log("关闭服务端", msg)
        self._update_run_state()

    def _kill_server(self) -> None:
        if not self.app.server.running:
            messagebox.showinfo("提示", "服务端未运行")
            return
        if not messagebox.askyesno(
            "强制结束",
            "直接终止进程，不会发维护公告、也不保存在线玩家状态。\n\n"
            "仅在服务端卡死不响应 shutdown 时使用。继续？",
        ):
            return
        ok, msg = self.app.server.kill()
        audit.log("强制结束服务端", msg)
        self._update_run_state()

    # ---- 读写 ----
    def load(self) -> None:
        cfg = self.app.server_config
        try:
            cfg.load()
        except Exception as e:
            messagebox.showerror("读取失败", str(e))
            return
        self.srv_port.set(str(cfg.get("Port", "30002")))
        choices_map = {
            k: EDITABLE[k][3] for k in self._choice_vars if len(EDITABLE[k]) > 3
        }
        for key, var in self._vars.items():
            val = cfg.get(key)
            if isinstance(var, tk.BooleanVar):
                var.set(bool(val))
            elif key in choices_map:
                # 下拉显示 "值 · 名称"；未知值原样显示，便于发现配置文件被手改
                opts = choices_map[key]
                try:
                    num = int(val)
                except (TypeError, ValueError):
                    num = None
                var.set(f"{num} · {opts[num]}" if num in opts else str(val))
            else:
                var.set("" if val is None else str(val))
        meta = cfg.metadata
        for key, var in self._meta_vars.items():
            var.set(bool(meta.get(key, False)))

        try:
            self.ini.load()
        except Exception as e:
            messagebox.showerror("launcher.ini 读取失败", str(e))
            return
        self.cli_ip.set(self.ini.get("ip", "127.0.0.1"))
        self._apply_delay()
        self._update_run_state()
        self.auth_port.set(str(self.app.auth.port))
        self._update_auth_state()

    def save(self) -> None:
        cfg = self.app.server_config

        # 服务端端口
        port = self.srv_port.get().strip()
        if not port.isdigit() or not (1 <= int(port) <= 65535):
            messagebox.showerror("输入错误", "服务端端口必须是 1-65535 的数字")
            return
        cfg.set("Port", port)

        for key, var in self._vars.items():
            typ = EDITABLE[key][1]
            raw = var.get()
            if typ is bool:
                cfg.set(key, bool(raw))
            elif key in self._choice_vars:
                # 下拉值形如 "6 · 万圣节"，取前半段数字
                head = str(raw).split("·")[0].strip()
                try:
                    cfg.set(key, int(head))
                except ValueError:
                    messagebox.showerror(
                        "输入错误", f"{EDITABLE[key][0]} 请从下拉列表中选择")
                    return
            elif typ is int:
                try:
                    cfg.set(key, int(str(raw).strip()))
                except ValueError:
                    messagebox.showerror("输入错误", f"{EDITABLE[key][0]} 必须是整数")
                    return
            else:
                cfg.set(key, str(raw))
        for key, var in self._meta_vars.items():
            cfg.set_metadata(key, var.get())

        problems = cfg.validate()
        if problems:
            messagebox.showerror(
                "校验失败", "配置未保存：\n\n" + "\n".join("· " + p for p in problems))
            return

        # 客户端连接地址：IP 单填，端口强制与服务端一致
        self.ini.set("ip", self.cli_ip.get())
        self.ini.set("port", port)
        ini_problems = self.ini.validate()
        if ini_problems:
            messagebox.showerror(
                "客户端地址有误", "未保存：\n\n" + "\n".join("· " + p for p in ini_problems))
            return

        try:
            backup = cfg.save(self.app.paths.backups_dir)
            ini_backup = self.ini.save(self.app.paths.backups_dir)
        except Exception as e:
            messagebox.showerror("保存失败", str(e))
            return

        audit.log(
            "保存配置",
            f"Port={port} 客户端={self.cli_ip.get()}:{port} "
            f"备份={backup.name if backup else '-'}/{ini_backup.name if ini_backup else '-'}",
        )
        # 端口变了要提醒
        changed_port = port != str(self.app.server_config.get("Port", port))
        messagebox.showinfo(
            "已保存",
            "ServerConfig.json 与 launcher.ini 已写入。\n\n"
            + ("⚠ 端口已修改，必须重启服务端才会生效。\n\n" if self.app.server.running else "")
            + "在线生效请点「重新加载服务端数据」。",
        )
        self._update_run_state()

    def _dbreload(self) -> None:
        if not self.app.server.running:
            messagebox.showwarning("服务端未运行", "配置会在下次启动时自动生效。")
            return
        if not messagebox.askyesno(
            "确认重载",
            "dbreload 会重建全部 Manager 并重新读取所有配置与数据库。\n\n"
            "官方标注为危险命令：配置有错误会让服务端直接关闭。\n\n继续？",
        ):
            return
        ok, msg = self.app.send_command("dbreload")
        if not ok:
            messagebox.showerror("发送失败", msg)
            return
        audit.log("dbreload", "服务端数据已重载")
        messagebox.showinfo("已下发", "dbreload 已发送，请到「运行与日志」页确认结果。")


__all__ = ["ConfigTab"]
