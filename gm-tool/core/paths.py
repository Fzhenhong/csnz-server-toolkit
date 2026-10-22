"""路径与运行配置。

工具放在服务端根目录下的 GM_Tool\ 里，默认以父目录为服务端根，
也可通过 config.json 的 server_root 覆盖（例如工具放到别处）。
"""
from __future__ import annotations

import json
import os
from pathlib import Path

TOOL_DIR = Path(__file__).resolve().parent.parent
CONFIG_PATH = TOOL_DIR / "config.json"

# 语言包：客户端解包出来的中文 token 表，用于把内部英文名翻成中文显示名
LANG_CANDIDATES = (
    "_unpack/resource/cso_chn.txt",
    "resource/cso_chn.txt",
    "CSNZ_Client/Bin/resource/cso_chn.txt",
    "CSNZ_Client/Data/resource/cso_chn.txt",
)

DEFAULTS = {
    "server_root": "..",
    "lang_file": "",
    "auto_backup": True,
    "max_backups": 50,
}


class Paths:
    """服务端各关键文件的位置。"""

    def __init__(self, root: Path, lang_file: str = "") -> None:
        self.root = Path(root).resolve()
        self._lang_file = lang_file

    # ---- 配置文件 ----
    @property
    def server_exe(self) -> Path:
        return self.root / "CSNZ_Server.exe"

    @property
    def server_config(self) -> Path:
        return self.root / "ServerConfig.json"

    @property
    def shop_json(self) -> Path:
        return self.root / "Shop.json"

    @property
    def launcher_ini(self) -> Path:
        return self.root / "launcher.ini"

    @property
    def item_csv(self) -> Path:
        return self.root / "Data" / "Item.csv"

    @property
    def db(self) -> Path:
        return self.root / "UserDatabase.db3"

    @property
    def logs_dir(self) -> Path:
        return self.root / "Logs"

    @property
    def backups_dir(self) -> Path:
        return TOOL_DIR / "backups"

    # ---- 语言包 ----
    @property
    def lang_file(self) -> Path | None:
        if self._lang_file:
            p = Path(self._lang_file)
            if not p.is_absolute():
                p = self.root / p
            return p if p.exists() else None
        for rel in LANG_CANDIDATES:
            p = self.root / rel
            if p.exists():
                return p
        return None

    def missing(self) -> list[str]:
        """返回缺失的必需文件，供 UI 提示。"""
        out = []
        for label, p in (
            ("CSNZ_Server.exe", self.server_exe),
            ("ServerConfig.json", self.server_config),
            ("UserDatabase.db3", self.db),
            ("Data/Item.csv", self.item_csv),
            ("Shop.json", self.shop_json),
            ("launcher.ini", self.launcher_ini),
        ):
            if not p.exists():
                out.append(label)
        return out


def load_config() -> dict:
    cfg = dict(DEFAULTS)
    if CONFIG_PATH.exists():
        try:
            cfg.update(json.loads(CONFIG_PATH.read_text(encoding="utf-8")))
        except Exception:
            pass
    return cfg


def save_config(cfg: dict) -> None:
    CONFIG_PATH.write_text(
        json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def build_paths(cfg: dict | None = None) -> Paths:
    cfg = cfg or load_config()
    root = Path(cfg.get("server_root") or "..")
    if not root.is_absolute():
        root = (TOOL_DIR / root).resolve()
    return Paths(root, cfg.get("lang_file") or "")


def resolve_root(cfg: dict | None = None) -> Path:
    return build_paths(cfg).root


__all__ = ["Paths", "TOOL_DIR", "CONFIG_PATH", "load_config", "save_config", "build_paths", "resolve_root"]
