"""16×16 线性图标，用 Canvas 绘制。

ttk 没有图标控件，Windows 上也没有可靠的图标字体（Segoe MDL2 的
codepoint 因系统版本而异）。这里用 Canvas 画线框，颜色可随主题变化，
在任何机器上渲染一致。

用法：
    icon_frame = theme.icon(parent, "users", theme.FG2, size=15)
"""
from __future__ import annotations

import tkinter as tk

SIZE = 16.0


def _draw(c: tk.Canvas, name: str, color: str, w: float = 1.4) -> None:
    """在 16×16 坐标系里画线。"""
    ln = lambda *pts, **kw: c.create_line(*pts, fill=color, width=kw.get("w", w),
                                          capstyle="round", joinstyle="round",
                                          smooth=kw.get("smooth", False))
    rect = lambda x1, y1, x2, y2: c.create_rectangle(x1, y1, x2, y2, outline=color,
                                                     width=w)
    oval = lambda x1, y1, x2, y2: c.create_oval(x1, y1, x2, y2, outline=color, width=w)

    if name == "grid":
        rect(2, 2, 7, 7)
        rect(9, 2, 14, 7)
        rect(2, 9, 7, 14)
        rect(9, 9, 14, 14)
    elif name == "term":
        rect(1.5, 2.5, 14.5, 13.5)
        ln(4, 6, 6.5, 8, 4, 10)
        ln(8.5, 10.5, 12, 10.5)
    elif name == "users":
        oval(2.5, 2, 7.5, 7)
        ln(1.5, 14, 1.5, 12.2, 2.4, 10.8, 4, 10.2, 6, 10.2, 7.6, 10.8, 8.5, 12.2, 8.5, 14)
        ln(10.8, 3.2, 12.6, 4.6, 12.6, 6.6, 11, 7.8)
        ln(10.5, 10.4, 12.2, 10.8, 13.6, 12.2, 14.5, 14)
    elif name == "box":
        ln(8, 1.8, 14, 5, 14, 11, 8, 14.2, 2, 11, 2, 5, 8, 1.8)
        ln(2, 5, 8, 8.2, 14, 5)
        ln(8, 8.2, 8, 14.2)
    elif name == "cart":
        ln(1, 2, 3.2, 2, 5.4, 10.6, 13, 10.6, 14.6, 5, 3.6, 5)
        oval(5.4, 12.4, 7.4, 14.4)
        oval(11.6, 12.4, 13.6, 14.4)
    elif name == "shield":
        ln(8, 1.6, 13.6, 4, 13.6, 8.2, 12, 11.4, 8, 14.4, 4, 11.4, 2.4, 8.2, 2.4, 4, 8, 1.6)
        ln(5.6, 7.8, 7.3, 9.5, 10.6, 6.2)
    elif name == "key":
        oval(1.6, 9.4, 5.8, 13.6)
        ln(4.6, 10.4, 13.2, 1.8)
        ln(10.4, 4.6, 12.6, 6.8)
        ln(8.2, 6.8, 10.4, 9)
    elif name == "sliders":
        for y in (4, 8, 12):
            ln(2, y, 14, y)
        rect(4.6, 2.4, 6.8, 5.6)
        rect(9, 6.4, 11.2, 9.6)
        rect(3.2, 10.4, 5.4, 13.6)
    elif name == "search":
        oval(2.4, 2.4, 10, 10)
        ln(9.4, 9.4, 13.8, 13.8)
    elif name == "alert":
        ln(8, 2.2, 14.6, 13.6, 1.4, 13.6, 8, 2.2)
        ln(8, 6, 8, 9.6)
        ln(8, 11.6, 8, 11.8)
    elif name == "info":
        oval(1.8, 1.8, 14.2, 14.2)
        ln(8, 7, 8, 11)
        ln(8, 4.6, 8, 4.8)
    elif name == "db":
        c.create_oval(2.4, 1.6, 13.6, 4.6, outline=color, width=w)
        ln(2.4, 3.1, 2.4, 12.9)
        ln(13.6, 3.1, 13.6, 12.9)
        c.create_arc(2.4, 10.4, 13.6, 15.4, start=180, extent=180,
                     style="arc", outline=color, width=w)
        c.create_arc(2.4, 6.4, 13.6, 11.4, start=180, extent=180,
                     style="arc", outline=color, width=w)
    elif name == "server":
        rect(1.6, 2.2, 14.4, 7)
        rect(1.6, 9, 14.4, 13.8)
        ln(4, 4.6, 4.2, 4.6)
        ln(4, 11.4, 4.2, 11.4)
    elif name == "clock":
        oval(1.8, 1.8, 14.2, 14.2)
        ln(8, 4.6, 8, 8.4, 10.6, 9.8)
    elif name == "x":
        ln(3.5, 3.5, 12.5, 12.5)
        ln(12.5, 3.5, 3.5, 12.5)


def paint(c: tk.Canvas, name: str, color: str, size: int = 15) -> None:
    """清空画布并重画图标（用于切换激活状态时改色）。"""
    c.delete("all")
    scale = size / SIZE
    before = set(c.find_all())
    _draw(c, name, color, w=max(1.2, 1.3 * scale))
    for i in set(c.find_all()) - before:
        c.scale(i, 0, 0, scale, scale)


def make(master, name: str, color: str, size: int = 15,
         bg: str = "#111721") -> tk.Canvas:
    """返回一个已画好图标的 Canvas。"""
    c = tk.Canvas(master, width=size, height=size, bg=bg,
                  highlightthickness=0, bd=0, takefocus=0)
    paint(c, name, color, size)
    return c


def draw_on(canvas: tk.Canvas, name: str, color: str, size: int = 15,
            x: int = 0, y: int = 0) -> None:
    """在已有 Canvas 的指定偏移处画图标（用于自绘按钮）。"""
    scale = size / SIZE
    ids_before = set(canvas.find_all())
    _draw(canvas, name, color, w=max(1.2, 1.3 * scale))
    for i in set(canvas.find_all()) - ids_before:
        canvas.scale(i, 0, 0, scale, scale)
        canvas.move(i, x, y)


__all__ = ["make", "draw_on"]
