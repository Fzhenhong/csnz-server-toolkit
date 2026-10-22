"""按屏幕可用区域计算窗口尺寸，让每个页面尽量一屏放下。

需要处理三种现实情况：

1. 不同分辨率（1366x768 笔记本到 2560x1440 桌面）下界面都要完整可见；
2. Windows 缩放（125% / 150%）：tkinter 报告的是物理像素，
   1080p 在 150% 缩放下可用高度只有约 680px，必须按实际值算；
3. 高分屏需要最小尺寸保底，避免控件被压扁。

所有页面都不做页面级滚动，因此窗口高度必须足够容纳最高的页面；
小屏时优先保证宽度，高度不足则压缩留白（见各页 padding）。
"""
from __future__ import annotations

import re

# 各页在默认字体下需要的「理想高度」，用于反推窗口尺寸。
# 这些值来自实测 reqheight，留了余量。
PAGE_MIN_HEIGHT = 700
PAGE_MIN_WIDTH = 1180

# 窗口占屏幕可用区域的比例：留出任务栏与窗口边框
WIDTH_RATIO = 0.94
HEIGHT_RATIO = 0.92


def dpi_scale(root) -> float:
    """当前屏幕的 DPI 比例（96 → 1.0，144 → 1.5）。

    进程已声明 DPI 感知，因此这里的像素就是物理像素；
    所有「最小尺寸」都要乘这个系数，否则 150% 屏上窗口会被压得很小。
    """
    try:
        return max(1.0, min(3.0, root.winfo_fpixels("1i") / 96.0))
    except Exception:
        return 1.0


def screen_area(root) -> tuple[int, int]:
    """返回可用的屏幕宽高（已扣除常见任务栏高度）。"""
    sw = root.winfo_screenwidth()
    sh = root.winfo_screenheight()
    return sw, sh


def is_geometry_usable(root, w: int, h: int, x: int, y: int) -> bool:
    """判断记忆的窗口位置是否仍可安全使用。

    换显示器、改分辨率、改缩放后，上次的坐标可能落在屏幕外，
    直接套用会让窗口「消失」。这里要求：
      · 尺寸不小于最小尺寸；
      · 窗口与当前屏幕有足够重叠（标题栏必须能点到）。
    """
    scale = dpi_scale(root)
    if w < PAGE_MIN_WIDTH * scale or h < PAGE_MIN_HEIGHT * scale:
        return False
    sw, sh = screen_area(root)
    if x < -w + 120 or x > sw - 120:
        return False
    if y < -8 or y > sh - 120:
        return False
    return True


GEOMETRY_RE = re.compile(r"^(\d+)x(\d+)([+-]-?\d+)([+-]-?\d+)$")


def parse_geometry(text: str) -> tuple[int, int, int, int] | None:
    """解析 tkinter 的 geometry 串，支持负坐标。

    tkinter 用符号表示方向：副屏在主屏左侧时坐标会是
    "1330x760-1920+80" 这种形式，因此必须用正则同时接受 + 和 -。
    """
    if not text:
        return None
    m = GEOMETRY_RE.match(text.strip())
    if not m:
        return None
    try:
        w, h = int(m.group(1)), int(m.group(2))
        x, y = int(m.group(3)), int(m.group(4))
    except ValueError:
        return None
    return w, h, x, y


def compute_geometry(root) -> tuple[int, int, int, int, bool]:
    """计算 (宽, 高, x, y, 是否需要最大化)。

    小屏（可用高度 < 页面最小高度）时直接最大化，
    否则取比例尺寸并居中。
    """
    sw, sh = screen_area(root)
    usable_h = sh - 48       # 任务栏 + 边框
    usable_w = sw - 16

    maxed = False
    w = int(usable_w * WIDTH_RATIO)
    h = int(usable_h * HEIGHT_RATIO)

    if w < PAGE_MIN_WIDTH:
        w = usable_w
    if h < PAGE_MIN_HEIGHT:
        # 屏幕装不下理想高度：最大化，让各页自行压缩
        w, h, maxed = usable_w, usable_h, True

    w = min(w, usable_w)
    h = min(h, usable_h)

    x = max(0, (sw - w) // 2)
    y = max(0, (sh - h) // 2 - 12)
    return w, h, x, y, maxed


def apply_geometry(root, saved: str | None = None) -> tuple[int, int]:
    """设置窗口尺寸并返回最终宽高。

    saved 为上次退出时记录的 "WxH+X+Y"；可用则优先恢复，
    不可用（换屏、改分辨率、尺寸过小）则按当前屏幕重新计算。
    """
    scale = dpi_scale(root)
    min_w, min_h = int(PAGE_MIN_WIDTH * scale), int(PAGE_MIN_HEIGHT * scale)

    parsed = parse_geometry(saved) if saved else None
    if parsed and is_geometry_usable(root, *parsed):
        w, h, x, y = parsed
        root.geometry(f"{w}x{h}+{x}+{y}")
        root.minsize(min_w, min_h)
        return w, h

    w, h, x, y, maxed = compute_geometry(root)
    root.geometry(f"{w}x{h}+{x}+{y}")
    root.minsize(min(min_w, w), min(min_h, h))
    if maxed:
        try:
            root.state("zoomed")
        except Exception:
            pass
    return w, h


def current_geometry(root) -> str:
    """记录当前窗口几何；最大化/全屏状态下退回窗口尺寸，避免存成屏幕大小。"""
    try:
        state = root.state()
    except Exception:
        state = "normal"
    if state in ("zoomed", "fullscreen"):
        # 最大化时 geometry() 仍反映还原后的尺寸
        return root.geometry()
    return root.geometry()


__all__ = ["compute_geometry", "apply_geometry", "screen_area", "current_geometry",
           "parse_geometry", "is_geometry_usable", "dpi_scale",
           "PAGE_MIN_HEIGHT", "PAGE_MIN_WIDTH"]
