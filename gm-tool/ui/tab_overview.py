"""总览页：服务端状态、数据源健康度、最近操作。

这一页只读，不做任何写操作——它的作用是「打开工具先看一眼」：
服务端在不在、有多少人在线、有没有封禁快到期、商城改动有没有重载。
"""
from __future__ import annotations

import re
import tkinter as tk
from datetime import datetime

from core import audit
from . import theme

P = theme.px

LINE_RE = re.compile(r"^\[(.{19})\]\s*([^|]*)(?:\|\s*(.*))?$")
NOTICE_COLORS = {
    "warn": ("#e8c88d", "#1e1a12", "#4a3a1c", theme.WARN),
    "danger": ("#f0a5a5", "#1f1618", "#4a2b30", theme.DANGER),
    "info": ("#a9c1e4", "#131b26", "#25384f", theme.ACCENT),
}


def notice(parent, title: str, text: str, kind: str = "info"):
    """左侧色条提示块（模拟 v2 的 notice）。"""
    fg, bg, bd, bar = NOTICE_COLORS.get(kind, NOTICE_COLORS["info"])
    box = tk.Frame(parent, bg=bg, highlightthickness=1, highlightbackground=bd)
    tk.Frame(box, bg=bar, width=2).pack(side="left", fill="y")
    inner = tk.Frame(box, bg=bg)
    inner.pack(side="left", fill="both", expand=True, padx=(P(9), P(10)), pady=(P(7), P(8)))
    tk.Label(inner, text=title, font=theme.FONT_S_B, fg=fg, bg=bg,
             anchor="w").pack(anchor="w")
    tk.Label(inner, text=text, font=theme.FONT_XS, fg=fg, bg=bg, anchor="w",
             justify="left", wraplength=P(300)).pack(anchor="w", pady=(P(3), P(0)))
    return box


class OverviewTab(tk.Frame):
    def __init__(self, master, app) -> None:
        super().__init__(master, bg=theme.L0)
        self.app = app
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
        tk.Label(left, text="总览", font=theme.FONT_TITLE, fg=theme.FG,
                 bg=theme.L0, anchor="w").pack(anchor="w")
        tk.Label(left, text="服务端运行状态、数据源健康度与最近操作。"
                            "所有写操作都会先自动备份数据库。",
                 font=theme.FONT_S, fg=theme.FG3, bg=theme.L0,
                 anchor="w").pack(anchor="w", pady=(P(3), P(0)))
        acts = tk.Frame(head, bg=theme.L0)
        acts.pack(side="right", anchor="n")
        theme.button(acts, "刷新", "ghost", self.refresh).pack(side="right")

        # KPI
        kpis = tk.Frame(outer, bg=theme.L0)
        kpis.pack(fill="x", pady=(P(14), P(0)))
        for i in range(4):
            kpis.columnconfigure(i, weight=1, uniform="kpi")
        self.kpi_online = self._kpi(kpis, 0, "users", "当前在线", "0", "/ -")
        self.kpi_users = self._kpi(kpis, 1, "db", "注册账号", "0", "")
        self.kpi_bans = self._kpi(kpis, 2, "shield", "封禁生效", "0", "")
        self.kpi_shop = self._kpi(kpis, 3, "cart", "商城在售", "0", "")

        # 主体两栏
        body = tk.Frame(outer, bg=theme.L0)
        body.pack(fill="both", expand=True, pady=(P(14), P(0)))
        body.columnconfigure(0, weight=155)
        body.columnconfigure(1, weight=100)
        body.rowconfigure(0, weight=1)

        lcol = tk.Frame(body, bg=theme.L0)
        lcol.grid(row=0, column=0, sticky="nsew", padx=(P(0), P(14)))
        lcol.columnconfigure(0, weight=1)
        lcol.rowconfigure(1, weight=1)

        rcol = tk.Frame(body, bg=theme.L0)
        rcol.grid(row=0, column=1, sticky="nsew")
        rcol.columnconfigure(0, weight=1)
        rcol.rowconfigure(1, weight=1)

        # --- 服务端 ---
        srv = theme.Card(lcol, "服务端", padding=0)
        srv.grid(row=0, column=0, sticky="ew")
        self.srv_pill_holder = tk.Frame(srv.head, bg=theme.L2)
        self.srv_pill_holder.pack(side="right", padx=(P(0), P(12)))
        self.srv_uptime = tk.Label(srv.head, text="", font=theme.FONT_MONO_S,
                                   fg=theme.FG3, bg=theme.L2)
        self.srv_uptime.pack(side="right", padx=(P(0), P(10)))

        sb = tk.Frame(srv.body, bg=theme.L2)
        sb.pack(fill="x", padx=P(14), pady=P(12))
        sb.columnconfigure(0, weight=1, uniform="srv")
        sb.columnconfigure(1, weight=1, uniform="srv")
        self._kv_grid(sb, 0, [("进程 PID", "-"), ("监听端口", "-"),
                              ("守护", "-")])
        self._kv_grid(sb, 1, [("客户端地址", "-"), ("数据库", "-"),
                              ("最近备份", "-")])

        # --- 最近操作 ---
        log_card = theme.Card(lcol, "最近操作", padding=0)
        log_card.grid(row=1, column=0, sticky="nsew", pady=(P(14), P(0)))
        tk.Label(log_card.head, text="审计日志", font=theme.FONT_S,
                 fg=theme.FG3, bg=theme.L2).pack(side="left")
        self.log_table = theme.Table(
            log_card.body, [("ts", "时间", 74), ("act", "操作", 104),
                       ("detail", "详情", 300, "w", True)],
            height=5, zebra=False,
        )
        self.log_table.pack(fill="both", expand=True, padx=P(1), pady=(P(0), P(1)))

        # --- 数据源 ---
        src = theme.Card(rcol, "数据源", padding=0)
        src.grid(row=0, column=0, sticky="ew")
        sbody = tk.Frame(src.body, bg=theme.L2)
        sbody.pack(fill="x", padx=P(13), pady=P(11))
        self.src_rows = {}
        for key, name in (("items", "道具表 Item.csv"), ("shop", "商城 Shop.json"),
                          ("db", "数据库 SQLite"), ("auth", "鉴权服务")):
            row = tk.Frame(sbody, bg=theme.L2)
            row.pack(fill="x", pady=P(3))
            tk.Label(row, text="●", font=(theme.FAMILY, 6), fg=theme.OK,
                     bg=theme.L2).pack(side="left")
            tk.Label(row, text=name, font=theme.FONT_S, fg=theme.FG2,
                     bg=theme.L2).pack(side="left", padx=(P(7), P(0)))
            val = tk.Label(row, text="-", font=theme.FONT_MONO_S, fg=theme.FG2,
                           bg=theme.L2)
            val.pack(side="right")
            self.src_rows[key] = val

        # --- 待处理 ---
        todo = theme.Card(rcol, "待处理", padding=0)
        todo.grid(row=1, column=0, sticky="nsew", pady=(P(14), P(0)))
        self.todo_count = tk.Label(todo.head, text="", font=theme.FONT_S,
                                   fg=theme.FG3, bg=theme.L2)
        self.todo_count.pack(side="right", padx=(P(0), P(12)))
        self.todo_body = tk.Frame(todo.body, bg=theme.L2)
        self.todo_body.pack(fill="both", expand=True, padx=P(12), pady=P(11))

    def _kpi(self, parent, col: int, icon_name: str, label: str,
             value: str, suffix: str) -> dict:
        card = theme.Card(parent, padding=0)
        card.grid(row=0, column=col, sticky="nsew",
                  padx=(0 if col == 0 else P(12), 0))
        inner = tk.Frame(card.body, bg=theme.L2)
        inner.pack(fill="both", expand=True, padx=P(13), pady=P(11))
        top = tk.Frame(inner, bg=theme.L2)
        top.pack(fill="x")
        theme.icon(top, icon_name, "#5b6b80", 13, theme.L2).pack(side="left")
        tk.Label(top, text=label, font=theme.FONT_S, fg=theme.FG3,
                 bg=theme.L2).pack(side="left", padx=(P(6), P(0)))
        val_row = tk.Frame(inner, bg=theme.L2)
        val_row.pack(fill="x", pady=(P(6), P(0)))
        val = tk.Label(val_row, text=value, font=(theme.MONO, 17, "bold"),
                       fg=theme.FG, bg=theme.L2, anchor="w")
        val.pack(side="left")
        sfx = tk.Label(val_row, text=suffix, font=theme.FONT_S, fg=theme.FG3,
                       bg=theme.L2, anchor="w")
        sfx.pack(side="left", padx=(P(5), P(0)), pady=(P(5), P(0)))
        sub = tk.Label(inner, text="", font=theme.FONT_XS, fg=theme.FG3,
                       bg=theme.L2, anchor="w")
        sub.pack(anchor="w", pady=(P(3), P(0)))
        return {"val": val, "suffix": sfx, "sub": sub}

    def _kv_grid(self, parent, col: int, rows: list[tuple[str, str]]) -> None:
        holder = tk.Frame(parent, bg=theme.L2)
        holder.grid(row=0, column=col, sticky="ew",
                    padx=(0, P(18)) if col == 0 else (0, 0))
        for i, (label, value) in enumerate(rows):
            row = tk.Frame(holder, bg=theme.L2)
            row.pack(fill="x", pady=P(2))
            tk.Label(row, text=label, font=theme.FONT_S, fg=theme.FG3,
                     bg=theme.L2, width=9, anchor="w").pack(side="left")
            tk.Label(row, text=value, font=theme.FONT_MONO_S, fg=theme.FG,
                     bg=theme.L2, anchor="w").pack(side="left", padx=(P(6), P(0)))
        setattr(self, f"_kvcol{col}", holder)

    # ---- 数据 ----
    def on_show(self) -> None:
        self.refresh()

    def refresh(self) -> None:
        app = self.app
        # KPI
        online = app.online_count if app.online_count >= 0 else 0
        max_p = app.server_config.get("MaxPlayers", 0) or "-"
        self.kpi_online["val"].configure(text=f"{online}")
        self.kpi_online["suffix"].configure(text=f"/ {max_p}")
        self.kpi_online["sub"].configure(text="UserSession 实时统计")

        try:
            users = app.db.list_users()
            total = len(users)
            banned = sum(1 for u in users if u.banned)
            today = sum(1 for u in users
                        if u.last_login and self._is_today(u.last_login))
        except Exception:
            total, banned, today = 0, 0, 0
        self.kpi_users["val"].configure(text=f"{total:,}")
        self.kpi_users["sub"].configure(text=f"今日登录 {today}")

        self.kpi_bans["val"].configure(text=f"{banned}")
        self.kpi_bans["sub"].configure(text="账号 · IP · HWID 三通道")

        products = len(app.shop.products)
        subs = sum(len(p.subs) for p in app.shop.products.values())
        self.kpi_shop["val"].configure(text=f"{products}")
        self.kpi_shop["suffix"].configure(text=f"件 / {subs} 档")
        self.kpi_shop["sub"].configure(
            text=f"推荐 {len(app.shop.recommended)} 页 · 热销 {len(app.shop.popular)} 件")

        # 服务端卡
        for w in self.srv_pill_holder.winfo_children():
            w.destroy()
        if app.server.running:
            theme.pill(self.srv_pill_holder, "运行中", "ok").pack()
            self.srv_uptime.configure(text=f"uptime {app.uptime_text}")
        else:
            theme.pill(self.srv_pill_holder, "未运行", "danger").pack()
            self.srv_uptime.configure(text="")

        cfg = app.server_config
        ini_ip = "-"
        try:
            from core.launcher_ini import LauncherIni
            ini = LauncherIni(app.paths.launcher_ini)
            ini.load()
            ini_ip = f"{ini.get('ip', '-')}:{ini.get('port', '-')}"
        except Exception:
            pass
        port = cfg.get("Port", "-")
        guard = "开启 · 掉线自启" if app.server.guarding else "未开启"
        self._fill_kv(0, [("进程 PID", str(app.server.pid or "-")),
                          ("监听端口", f"{port}  TCP/UDP"),
                          ("守护", guard)])
        self._fill_kv(1, [("客户端地址", ini_ip),
                          ("数据库", f"schema v{app._schema_version()}"),
                          ("最近备份", app._last_backup)])

        # 最近操作
        rows = []
        for line in reversed(audit.tail(60)):
            m = LINE_RE.match(line)
            if not m:
                continue
            rows.append((m.group(1)[11:19], m.group(2).strip(),
                         (m.group(3) or "").strip()))
            if len(rows) >= 5:
                break
        self.log_table.set_rows(rows)

        # 数据源
        self.src_rows["items"].configure(text=f"{len(app.items):,} 条")
        self.src_rows["shop"].configure(text=f"{products} 商品")
        self.src_rows["db"].configure(
            text=f"v{app._schema_version()}")
        auth_ok = bool(str(app.cfg.get("auth_base_url", "")).startswith("http"))
        self.src_rows["auth"].configure(
            text="已配置" if auth_ok else "未配置",
            fg=theme.OK if auth_ok else theme.FG3)

        # 待处理
        for w in self.todo_body.winfo_children():
            w.destroy()
        items = []
        if banned:
            items.append(("warn", f"{banned} 个封禁生效中",
                          "双击封禁列表可解封；静默封不会告知客户端原因。"))
        shop_tab = getattr(app, "tab_shop", None)
        if shop_tab is not None and getattr(shop_tab, "_pending_reload", False):
            items.append(("info", "商城改动未重载",
                          "保存 Shop.json 后必须 dbreload 才会同步到客户端。"))
        if not app.server.running:
            items.append(("danger", "服务端未运行",
                          "顶栏可启动；启动后守护会自动接管掉线重启。"))
        if not items:
            items.append(("info", "没有待处理事项",
                          "服务端运行正常，配置与商城均无未生效改动。"))
        for kind, title, text in items[:3]:
            notice(self.todo_body, title, text, kind).pack(fill="x", pady=(P(0), P(7)))
        self.todo_count.configure(text=f"{len(items)} 项")

    def _fill_kv(self, col: int, rows: list[tuple[str, str]]) -> None:
        holder = getattr(self, f"_kvcol{col}", None)
        if holder is None:
            return
        for w in holder.winfo_children():
            w.destroy()
        for label, value in rows:
            row = tk.Frame(holder, bg=theme.L2)
            row.pack(fill="x", pady=P(2))
            tk.Label(row, text=label, font=theme.FONT_S, fg=theme.FG3,
                     bg=theme.L2, width=9, anchor="w").pack(side="left")
            tk.Label(row, text=value, font=theme.FONT_MONO_S, fg=theme.FG,
                     bg=theme.L2, anchor="w").pack(side="left", padx=(P(6), P(0)))

    @staticmethod
    def _is_today(minutes_ts: int) -> bool:
        try:
            d = datetime.fromtimestamp(minutes_ts * 60)
            return d.date() == datetime.now().date()
        except Exception:
            return False


__all__ = ["OverviewTab"]
