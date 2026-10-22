"""CSNZ GM 管理工具入口。

用法：
    把 GM_Tool 整个目录放到 CSNZ 服务端根目录（与 CSNZ_Server.exe 同级），
    双击 启动.bat，或执行 python main.py。

若工具放在别处，改 config.json 的 server_root 为服务端绝对路径。
"""
from __future__ import annotations

import sys
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))


def main() -> int:
    try:
        from ui.app import main as run
        run()
        return 0
    except Exception:
        err = traceback.format_exc()
        try:
            from tkinter import messagebox, Tk
            root = Tk()
            root.withdraw()
            messagebox.showerror("GM 工具启动失败", err)
        except Exception:
            print(err, file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
