"""操作审计。

服务端本身没有管理员操作日志，所有改动只能在工具侧留痕，
否则一旦出事无法回溯是谁在什么时候改了谁的号。
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

from .paths import TOOL_DIR

AUDIT_PATH = TOOL_DIR / "logs" / "audit.log"


def log(action: str, detail: str = "") -> None:
    AUDIT_PATH.parent.mkdir(parents=True, exist_ok=True)
    line = f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {action}"
    if detail:
        line += f" | {detail}"
    try:
        with AUDIT_PATH.open("a", encoding="utf-8") as f:
            f.write(line.replace("\n", " ") + "\n")
    except OSError:
        pass


def tail(limit: int = 500) -> list[str]:
    if not AUDIT_PATH.exists():
        return []
    lines = AUDIT_PATH.read_text(encoding="utf-8", errors="replace").splitlines()
    return lines[-limit:]


__all__ = ["log", "tail", "AUDIT_PATH"]
