"""CSNZ 服务端管理工具 · 视觉主题 v2。

设计取向：深色控制台。四级表面 + 单一强调色 + 四个状态色，语义固定不混用。

表面层级（每级只承担一个语义）：
    L0  应用底 / 顶栏 / 状态栏
    L1  侧栏 / 表头
    L2  卡片 / 表格
    L3  输入框 / 按钮
    L4  悬停

强调色只用于「可交互 / 选中 / 进行中」；状态色只用于状态，不用于装饰。
正文 12px、辅助 11px，对比度分别为 14:1 / 5.6:1，满足 WCAG AA。

ttk(clam) 不支持圆角与阴影，卡片用 1px 高亮边框 + 表面色差表达层级。
"""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from . import icons

# ---------- 表面 ----------
L0 = "#0b0f15"
L1 = "#111721"
L2 = "#161e29"
L3 = "#1c2531"
L4 = "#243040"
LINE = "#212c3a"
LINE2 = "#2d3a4b"

# ---------- 文字 ----------
FG = "#e8edf5"
FG2 = "#9dabbe"
FG3 = "#7a889b"
FG_DIS = "#556172"

# ---------- 语义色 ----------
ACCENT = "#4c8dff"
ACCENT_INK = "#2f6fe0"
ACCENT_HOVER = "#3b7bf0"
ACCENT_BG = "#1d2c45"
OK = "#35d399"
OK_BG = "#16302a"
WARN = "#f5b547"
WARN_BG = "#332d21"
DANGER = "#f86b6b"
DANGER_BG = "#33232a"
PURPLE = "#a78bfa"
PURPLE_BG = "#282c44"

# ---------- 兼容旧名（旧页面仍引用） ----------
BG = L0
PANEL = L2
RAISED = L3
HOVER = L4
BORDER = LINE
MUTED = FG3
DIM = FG3
ACCENT_DIM = ACCENT_INK
ZEBRA = "#191f2a"
ROW_ONLINE = "#16241f"
ROW_BANNED = "#2a1c20"
ROW_OWNED = "#1b2536"
ROW_WARN = "#2a2519"
LOG_BG = "#080b10"
LOG_FG = "#c3cedd"
LOG_ERR = "#e86a6a"
LOG_WARN = "#d9a948"
LOG_CMD = "#79b8ff"
LOG_TS = "#5d6b7e"

# ---------- 字体（96dpi 下 9pt ≈ 12px） ----------
FAMILY = "Microsoft YaHei UI"
MONO = "Consolas"
FONT = (FAMILY, 9)
FONT_S = (FAMILY, 8)
FONT_XS = (FAMILY, 7)
FONT_BOLD = (FAMILY, 9, "bold")
FONT_S_B = (FAMILY, 8, "bold")
FONT_MD = (FAMILY, 10)
FONT_H = (FAMILY, 11, "bold")
FONT_TITLE = (FAMILY, 12, "bold")
FONT_SUB = (FAMILY, 9)
FONT_MONO = (MONO, 9)
FONT_MONO_S = (MONO, 8)
FONT_MONO_B = (MONO, 9, "bold")

ROW_H = 30          # 逻辑行高，实际值 = px(ROW_H)
SCALE = 1.0         # 由 init_scale() 按屏幕 DPI 设定（96→1.0，144→1.5）


def init_scale(root: tk.Misc) -> float:
    """读取真实 DPI 比例。必须在创建任何控件之前调用。"""
    global SCALE
    try:
        SCALE = max(1.0, min(3.0, root.winfo_fpixels("1i") / 96.0))
    except Exception:
        SCALE = 1.0
    return SCALE


def px(n: float) -> int:
    """逻辑像素 → 物理像素。所有硬编码尺寸都必须经过它，
    否则在 150% 屏上间距会缩成 2/3，页面看起来「挤」。"""
    return int(round(n * SCALE))


def apply(root: tk.Misc) -> ttk.Style:
    """注册全部 ttk 样式。只能调用一次。"""
    # 声明 DPI 感知后 winfo_fpixels('1i') 返回真实 DPI（96 / 120 / 144）。
    # Tk 默认按 72 当作一英寸，不校正的话 9pt 字在 150% 屏上只有 8 逻辑像素。
    init_scale(root)
    try:
        root.tk.call("tk", "scaling", root.winfo_fpixels("1i") / 72.0)
    except Exception:
        pass

    style = ttk.Style(root)
    try:
        style.theme_use("clam")
    except tk.TclError:
        pass

    style.configure(".", font=FONT, background=L0, foreground=FG)
    style.configure("TFrame", background=L2)
    style.configure("Root.TFrame", background=L0)
    style.configure("Side.TFrame", background=L1)
    style.configure("Bar.TFrame", background=L0)
    style.configure("Card.TFrame", background=L2)
    style.configure("Inner.TFrame", background=L2)

    # ---- 文字 ----
    style.configure("TLabel", background=L0, foreground=FG, font=FONT)
    style.configure("Card.TLabel", background=L2, foreground=FG, font=FONT)
    style.configure("Title.TLabel", background=L0, foreground=FG, font=FONT_TITLE)
    style.configure("Head.TLabel", background=L2, foreground=FG, font=FONT_BOLD)
    style.configure("Sub.TLabel", background=L2, foreground=FG3, font=FONT_S)
    style.configure("SubBar.TLabel", background=L0, foreground=FG3, font=FONT_S)
    style.configure("Muted.TLabel", background=L2, foreground=FG3, font=FONT_S)
    style.configure("MutedCard.TLabel", background=L2, foreground=FG3, font=FONT_S)
    style.configure("Field.TLabel", background=L2, foreground=FG3, font=FONT_S)
    style.configure("Panel.TLabel", background=L2, foreground=FG, font=FONT)
    style.configure("Ok.TLabel", background=L2, foreground=OK, font=FONT_BOLD)
    style.configure("Danger.TLabel", background=L2, foreground=DANGER, font=FONT_BOLD)
    style.configure("Warn.TLabel", background=L2, foreground=WARN, font=FONT_BOLD)
    style.configure("Online.TLabel", background=L2, foreground=ACCENT, font=FONT_BOLD)

    # ---- 按钮 ----
    style.configure("TButton", font=FONT, background=L3, foreground=FG,
                    borderwidth=1, bordercolor=LINE2, focusthickness=0,
                    padding=(px(11), px(4)), relief="flat")
    style.map("TButton",
              background=[("pressed", L4), ("active", L4), ("disabled", L2)],
              bordercolor=[("active", "#3a4a5e")],
              foreground=[("disabled", FG_DIS)])

    style.configure("Primary.TButton", font=FONT_BOLD, background=ACCENT_INK,
                    foreground="#ffffff", borderwidth=1, bordercolor="#3d7bef",
                    padding=(px(12), px(4)))
    style.map("Primary.TButton",
              background=[("pressed", "#2a63ca"), ("active", ACCENT_HOVER),
                          ("disabled", L3)],
              foreground=[("disabled", FG_DIS)])

    style.configure("Ghost.TButton", font=FONT, background=L2, foreground=FG2,
                    borderwidth=1, bordercolor=L2, padding=(px(8), px(3)))
    style.map("Ghost.TButton",
              background=[("active", L3), ("pressed", L4)],
              bordercolor=[("active", LINE2)],
              foreground=[("active", FG), ("disabled", FG_DIS)])

    style.configure("DangerGhost.TButton", font=FONT, background=L2, foreground="#ff9d9d",
                    borderwidth=1, bordercolor="#4a2b30", padding=(px(11), px(3)))
    style.map("DangerGhost.TButton",
              background=[("active", DANGER_BG), ("pressed", "#3d262c")],
              bordercolor=[("active", "#6b3b42")])

    style.configure("DangerSolid.TButton", font=FONT_BOLD, background="#c84848",
                    foreground="#ffffff", borderwidth=1, bordercolor="#d95656",
                    padding=(px(12), px(4)))
    style.map("DangerSolid.TButton",
              background=[("pressed", "#b03c3c"), ("active", "#d75757")])

    style.configure("Danger.TButton", font=FONT, background=L2, foreground="#ff9d9d",
                    borderwidth=1, bordercolor="#4a2b30", padding=(px(11), px(3)))
    style.map("Danger.TButton", background=[("active", DANGER_BG)])
    style.configure("Accent.TButton", font=FONT_BOLD, background=ACCENT_INK,
                    foreground="#ffffff", borderwidth=1, bordercolor="#3d7bef",
                    padding=(px(12), px(4)))
    style.map("Accent.TButton", background=[("active", ACCENT_HOVER),
                                            ("pressed", "#2a63ca")])

    # ---- 输入 ----
    for name in ("TEntry", "TSpinbox"):
        style.configure(name, fieldbackground=L3, background=L3, foreground=FG,
                        insertcolor=FG, borderwidth=1, bordercolor=LINE2,
                        lightcolor=L3, darkcolor=L3, relief="flat", padding=px(4))
        style.map(name,
                  bordercolor=[("focus", ACCENT), ("active", "#3a4a5e")],
                  fieldbackground=[("disabled", L2), ("readonly", L2)],
                  foreground=[("disabled", FG_DIS)])
    style.configure("TCombobox", fieldbackground=L3, background=L3, foreground=FG,
                    bordercolor=LINE2, lightcolor=L3, darkcolor=L3,
                    arrowcolor=FG3, borderwidth=1, padding=px(3))
    style.map("TCombobox",
              fieldbackground=[("readonly", L3), ("disabled", L2)],
              foreground=[("readonly", FG)],
              bordercolor=[("focus", ACCENT), ("active", "#3a4a5e")],
              selectbackground=[("readonly", L3)],
              selectforeground=[("readonly", FG)])
    root.option_add("*TCombobox*Listbox.background", L2)
    root.option_add("*TCombobox*Listbox.foreground", FG)
    root.option_add("*TCombobox*Listbox.selectBackground", ACCENT_INK)
    root.option_add("*TCombobox*Listbox.selectForeground", "#ffffff")
    root.option_add("*TCombobox*Listbox.font", FONT)
    root.option_add("*TCombobox*Listbox.borderWidth", 1)

    # ---- 勾选 ----
    style.configure("TCheckbutton", background=L2, foreground=FG2, font=FONT,
                    focusthickness=0, indicatorcolor=L3,
                    indicatorbackground=L3, indicatorforeground=ACCENT)
    style.map("TCheckbutton",
              background=[("active", L2)],
              indicatorcolor=[("selected", ACCENT_INK), ("pressed", L4)],
              indicatorbackground=[("selected", ACCENT_INK), ("pressed", L4),
                                   ("!selected", L3)],
              foreground=[("active", FG), ("disabled", FG_DIS)])
    style.configure("BarCheck.TCheckbutton", background=L0, foreground=FG3, font=FONT_S)
    style.map("BarCheck.TCheckbutton", background=[("active", L0)])

    # ---- 分隔 ----
    style.configure("TSeparator", background=LINE)
    style.configure("TLabelframe", background=L2, foreground=FG,
                    borderwidth=1, relief="solid", bordercolor=LINE)
    style.configure("TLabelframe.Label", background=L2, foreground=FG, font=FONT_BOLD)

    # ---- 表格 ----
    style.configure("Treeview", font=FONT, rowheight=ROW_H, background=L2,
                    fieldbackground=L2, foreground=FG, borderwidth=0,
                    bordercolor=L2, lightcolor=L2, darkcolor=L2, relief="flat", padding=0)
    style.configure("Treeview.Heading", font=FONT_S_B, background=L1,
                    foreground=FG3, relief="flat", padding=(px(8), px(7)), borderwidth=0,
                    bordercolor=LINE, lightcolor=L1, darkcolor=L1)
    style.map("Treeview.Heading",
              background=[("active", L3)],
              foreground=[("active", FG)])
    style.map("Treeview",
              background=[("selected", ACCENT_BG)],
              foreground=[("selected", "#ffffff")])


    # ---- 滚动条 ----
    for orient in ("Vertical", "Horizontal"):
        style.configure(f"{orient}.TScrollbar", background="#2a3646",
                        troughcolor=L2, borderwidth=0, bordercolor=L2,
                        lightcolor=L2, darkcolor=L2, arrowcolor=L2,
                        gripcount=0, width=px(9), arrowsize=px(10))
        style.map(f"{orient}.TScrollbar",
                  background=[("active", "#3a4a5e"), ("pressed", "#4a5a70")],
                  arrowcolor=[("active", L2), ("pressed", L2)])

    # ---- 导航（旧 Notebook，保留给未迁移页面） ----
    style.configure("TNotebook", background=L0, borderwidth=0, tabmargins=(px(8), px(6), px(8), 0))
    style.configure("TNotebook.Tab", font=FONT, background=L0, foreground=FG3,
                    padding=(px(18), px(9)), borderwidth=0)
    style.map("TNotebook.Tab",
              background=[("selected", L2), ("active", L3)],
              foreground=[("selected", ACCENT), ("active", FG)])

    return style


# ============================================================
# 组件
# ============================================================
class Card(tk.Frame):
    """1px 描边卡片。head 放右侧控件，body 放内容。"""

    def __init__(self, master, title: str | None = None, padding: int = 12,
                 subtitle: str | None = None, bg: str = L2) -> None:
        super().__init__(master, bg=bg, highlightthickness=1,
                         highlightbackground=LINE, highlightcolor=LINE, bd=0)
        self.head: tk.Frame | None = None
        if title is not None:
            head = tk.Frame(self, bg=bg, height=px(36))
            head.pack(fill="x")
            head.pack_propagate(False)
            tk.Label(head, text=title, font=FONT_BOLD, fg=FG, bg=bg).pack(
                side="left", padx=(px(12), px(8)))
            if subtitle:
                tk.Label(head, text=subtitle, font=FONT_S, fg=FG3, bg=bg).pack(
                    side="left")
            self.head = head
            tk.Frame(self, bg=LINE, height=1).pack(fill="x")
        self.body = tk.Frame(self, bg=bg)
        if padding:
            self.body.pack(fill="both", expand=True, padx=px(padding), pady=px(padding))
        else:
            self.body.pack(fill="both", expand=True)


def icon(master, name: str, color: str = FG3, size: int = 15,
         bg: str = L1) -> tk.Canvas:
    return icons.make(master, name, color, size=size, bg=bg)


PILL_COLORS = {
    "ok": (OK, OK_BG, "#2a5f4c"),
    "danger": (DANGER, DANGER_BG, "#5c3138"),
    "warn": (WARN, WARN_BG, "#5c4a28"),
    "accent": (ACCENT, ACCENT_BG, "#2f4a75"),
    "gm": (PURPLE, PURPLE_BG, "#453e6b"),
    "muted": (FG3, L3, LINE2),
}


def pill(master, text: str, kind: str = "muted", bg: str = L2,
         dot: bool = True) -> tk.Label:
    fg, fill, bd = PILL_COLORS.get(kind, PILL_COLORS["muted"])
    return tk.Label(
        master, text=("● " if dot else "") + text, font=FONT_S_B, fg=fg, bg=fill,
        padx=px(6), pady=px(1), bd=0, highlightthickness=1, highlightbackground=bd,
    )


def button(master, text: str, kind: str = "default", command=None,
           width: int | None = None, **kw) -> ttk.Button:
    styles = {
        "default": "TButton", "primary": "Primary.TButton", "ghost": "Ghost.TButton",
        "danger": "DangerGhost.TButton", "danger-solid": "DangerSolid.TButton",
    }
    b = ttk.Button(master, text=text, style=styles.get(kind, "TButton"),
                   command=command, **kw)
    if width:
        b.configure(width=width)
    return b


def hline(master, bg: str = L2, color: str = LINE) -> tk.Frame:
    f = tk.Frame(master, bg=color, height=1)
    f.pack(fill="x")
    return f


def section(master, text: str, bg: str = L2) -> tk.Frame:
    """小标题 + 右侧延伸的分隔线。"""
    row = tk.Frame(master, bg=bg)
    row.pack(fill="x")
    tk.Label(row, text=text, font=FONT_XS, fg="#61718a", bg=bg).pack(side="left")
    tk.Frame(row, bg=LINE, height=1).pack(side="left", fill="x", expand=True,
                                          padx=(px(8), 0))
    return row


def kv_row(parent, label: str, value: str, bg: str = L2,
           mono: bool = True) -> tuple[tk.Label, tk.Label]:
    lb = tk.Label(parent, text=label, font=FONT_S, fg=FG3, bg=bg, anchor="w")
    val = tk.Label(parent, text=value, font=FONT_MONO_S if mono else FONT_S,
                   fg=FG, bg=bg, anchor="e")
    return lb, val


def scroll_area(master, bg: str = L0) -> tuple[tk.Frame, tk.Frame]:
    """可纵向滚动的容器。返回 (outer, inner)，内容放进 inner。"""
    outer = tk.Frame(master, bg=bg)
    canvas = tk.Canvas(outer, bg=bg, highlightthickness=0, bd=0)
    vsb = ttk.Scrollbar(outer, orient="vertical", command=canvas.yview)
    canvas.configure(yscrollcommand=vsb.set)
    canvas.pack(side="left", fill="both", expand=True)
    vsb.pack(side="right", fill="y")
    inner = tk.Frame(canvas, bg=bg)
    win = canvas.create_window((0, 0), window=inner, anchor="nw")
    inner.bind("<Configure>",
               lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
    canvas.bind("<Configure>",
                lambda e: canvas.itemconfigure(win, width=e.width))

    def _wheel(event):
        if _pointer_inside(canvas):
            canvas.yview_scroll(int(-event.delta / 120), "units")

    canvas.bind_all("<MouseWheel>", _wheel, add="+")
    return outer, inner


def _pointer_inside(widget) -> bool:
    try:
        x, y = widget.winfo_pointerxy()
        w = widget.winfo_containing(x, y)
        while w is not None:
            if w is widget:
                return True
            w = w.master
    except Exception:
        return False
    return False


def page(container, title: str, desc: str = "", pad: int = 18
         ) -> tuple[tk.Frame, tk.Frame]:
    """页面骨架：返回 (内容容器, 右侧操作区)。

    所有页面统一用 18px 外边距 + 标题/描述 + 右上角操作按钮，
    避免每个页面各写一遍导致间距不一致。
    """
    outer = tk.Frame(container, bg=L0)
    outer.pack(fill="both", expand=True, padx=px(pad), pady=(px(14), px(14)))
    head = tk.Frame(outer, bg=L0)
    head.pack(fill="x")
    left = tk.Frame(head, bg=L0)
    left.pack(side="left", fill="x", expand=True)
    tk.Label(left, text=title, font=FONT_TITLE, fg=FG, bg=L0,
             anchor="w").pack(anchor="w")
    if desc:
        tk.Label(left, text=desc, font=FONT_S, fg=FG3, bg=L0, anchor="w",
                 justify="left").pack(anchor="w", pady=(px(3), 0))
    acts = tk.Frame(head, bg=L0)
    acts.pack(side="right", anchor="n")
    return outer, acts


def search_box(parent, var, width: int = 26, bg: str = L0) -> tk.Frame:
    """带放大镜图标的输入框（tk.Entry 没有内嵌图标）。"""
    box = tk.Frame(parent, bg=L3, highlightthickness=1,
                   highlightbackground=LINE2)
    icons.make(box, "search", "#5f6f85", px(13), L3).pack(
        side="left", padx=(px(8), 0))
    ent = tk.Entry(box, textvariable=var, font=FONT, bg=L3, fg=FG,
                   insertbackground=FG, bd=0, highlightthickness=0,
                   width=width)
    ent.pack(side="left", padx=(px(6), px(8)), pady=px(5))
    box.entry = ent  # type: ignore[attr-defined]
    return box


class Table(tk.Frame):
    """深色表格：固定表头、可排序、状态着色、等宽数字列。

    columns: [(key, 标题, 宽度, 对齐)]，对齐取 "w" / "e" / "center"。
    """

    def __init__(self, master, columns, height=10, on_select=None,
                 on_double=None, zebra: bool = True, bg: str = L2) -> None:
        super().__init__(master, bg=bg, highlightthickness=0, bd=0)
        self._columns = columns
        self._sort_key: str | None = None
        self._sort_desc = False
        self._rows: list[tuple] = []
        self._zebra = zebra

        keys = [c[0] for c in columns]
        self.tree = ttk.Treeview(self, columns=keys, show="headings",
                                 height=height, selectmode="browse")
        for col in columns:
            key, title, width = col[0], col[1], col[2]
            anchor = col[3] if len(col) > 3 else "w"
            stretch = bool(col[4]) if len(col) > 4 else False
            self.tree.heading(key, text=title, anchor=anchor,
                              command=lambda k=key: self._sort_by(k))
            self.tree.column(key, width=px(width),
                             minwidth=max(px(34), px(width // 2)),
                             anchor=anchor, stretch=stretch)

        vsb = ttk.Scrollbar(self, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=vsb.set)
        self.tree.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")
        self.rowconfigure(0, weight=1)
        self.columnconfigure(0, weight=1)

        self.tree.tag_configure("online", background=ROW_ONLINE, foreground="#8fe6c3")
        self.tree.tag_configure("banned", background=ROW_BANNED, foreground="#ffa8a8")
        self.tree.tag_configure("owned", background=ROW_OWNED, foreground="#a8c4ff")
        self.tree.tag_configure("warn", background=ROW_WARN, foreground="#f3c47a")
        self.tree.tag_configure("zebra", background=ZEBRA)
        self.tree.tag_configure("muted", foreground=FG3)

        if on_select:
            self.tree.bind("<<TreeviewSelect>>", lambda e: on_select())
        if on_double:
            self.tree.bind("<Double-1>", lambda e: on_double())

    def set_rows(self, rows: list[tuple], tags: list[str] | None = None) -> None:
        self._rows = rows
        current = self.selected_index()
        self.tree.delete(*self.tree.get_children())
        for i, row in enumerate(rows):
            tag = tags[i] if tags else ""
            if not tag and self._zebra and i % 2 == 1:
                tag = "zebra"
            self.tree.insert("", "end", iid=str(i), values=row,
                             tags=(tag,) if tag else ())
        if current is not None and current < len(rows):
            self.tree.selection_set(str(current))

    def selected_index(self) -> int | None:
        sel = self.tree.selection()
        return int(sel[0]) if sel else None

    def selected_id(self) -> int | None:
        return self.selected_index()

    def selected_row(self) -> tuple | None:
        idx = self.selected_index()
        return self._rows[idx] if idx is not None and idx < len(self._rows) else None

    def _sort_by(self, key: str) -> None:
        keys = [c[0] for c in self._columns]
        if key not in keys:
            return
        pos = keys.index(key)
        if self._sort_key == key:
            self._sort_desc = not self._sort_desc
        else:
            self._sort_key, self._sort_desc = key, False

        def sort_val(row):
            v = row[pos] if pos < len(row) else ""
            s = str(v)
            try:
                return (0, float(s.replace(",", "")))
            except ValueError:
                return (1, s)

        self._rows.sort(key=sort_val, reverse=self._sort_desc)
        self.set_rows(self._rows)


def scroll_text(master, height=12, mono=True, bg: str = L2) -> tk.Frame:
    """深色多色日志视图。"""
    frame = tk.Frame(master, bg=bg, highlightthickness=0, bd=0)
    text = tk.Text(
        frame, height=height, wrap="none",
        font=FONT_MONO if mono else FONT,
        background=LOG_BG, foreground=LOG_FG,
        insertbackground=LOG_FG, borderwidth=0, highlightthickness=0,
        padx=px(10), pady=px(8), spacing1=1, spacing3=1,
    )
    vsb = ttk.Scrollbar(frame, orient="vertical", command=text.yview)
    hsb = ttk.Scrollbar(frame, orient="horizontal", command=text.xview)
    text.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)
    text.grid(row=0, column=0, sticky="nsew")
    vsb.grid(row=0, column=1, sticky="ns")
    hsb.grid(row=1, column=0, sticky="ew")
    frame.rowconfigure(0, weight=1)
    frame.columnconfigure(0, weight=1)
    text.tag_configure("err", foreground=LOG_ERR)
    text.tag_configure("warn", foreground=LOG_WARN)
    text.tag_configure("cmd", foreground=LOG_CMD)
    text.tag_configure("ts", foreground=LOG_TS)
    text.tag_configure("ok", foreground="#4fbf94")
    frame.text = text  # type: ignore[attr-defined]
    return frame


def append_log(widget, line: str, tag: str = "") -> None:
    text = widget.text  # type: ignore[attr-defined]
    at_bottom = text.yview()[1] > 0.98
    text.insert("end", line + "\n", tag or ())
    if at_bottom:
        text.see("end")


def hsep(master, pad=(0, 8)) -> ttk.Separator:
    sep = ttk.Separator(master, orient="horizontal")
    sep.pack(fill="x", pady=pad)
    return sep


def badge(master, text: str, kind: str = "muted") -> tk.Label:
    """旧接口，映射到新 pill。"""
    return pill(master, text, kind, bg=L0)


__all__ = [
    "L0", "L1", "L2", "L3", "L4", "LINE", "LINE2", "FG", "FG2", "FG3", "FG_DIS",
    "ACCENT", "ACCENT_INK", "ACCENT_HOVER", "ACCENT_BG", "OK", "OK_BG",
    "WARN", "WARN_BG", "DANGER", "DANGER_BG", "PURPLE", "PURPLE_BG",
    "BG", "PANEL", "RAISED", "HOVER", "BORDER", "MUTED", "DIM", "ACCENT_DIM",
    "ZEBRA", "ROW_ONLINE", "ROW_BANNED", "ROW_OWNED", "ROW_WARN",
    "LOG_BG", "LOG_FG", "LOG_ERR", "LOG_WARN", "LOG_CMD", "LOG_TS",
    "FAMILY", "MONO", "FONT", "FONT_S", "FONT_XS", "FONT_BOLD", "FONT_S_B",
    "FONT_MD", "FONT_H", "FONT_TITLE", "FONT_SUB", "FONT_MONO", "FONT_MONO_S",
    "FONT_MONO_B", "ROW_H", "PILL_COLORS", "SCALE", "px", "init_scale",
    "apply", "Card", "icon", "pill", "button", "hline", "section", "kv_row",
    "scroll_area", "page", "search_box", "Table", "scroll_text", "append_log", "hsep", "badge",
]
