"""launcher.ini 读写（客户端启动器配置）。

这是玩家实际要连的地址，和 ServerConfig.Port（服务端监听端口）是两回事：
· ServerConfig.Port   服务端绑哪个端口 —— 监听地址写死在代码里（getaddrinfo 传 NULL
                      + AI_PASSIVE，即 0.0.0.0），所以只能改端口不能改绑定 IP；
· launcher.ini        客户端连哪个 IP/端口 —— 这才是对外发给玩家要填的东西。

文件格式注意：
· 带 UTF-8 BOM（EF BB BF），必须原样保留，否则启动器按 ANSI 读取会乱码；
· 换行是 CRLF；
· 第一行是以 ; 开头的注释。
"""
from __future__ import annotations

import shutil
from datetime import datetime
from pathlib import Path

BOM = "\ufeff"
DEFAULT_CLIENT = "CSNZ_Client\\Bin"


class LauncherIni:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.entries: dict[str, str] = {}
        self.comment_lines: list[str] = []
        self.dirty = False
        self.exists = False

    # ---- 读写 ----
    def load(self) -> None:
        self.entries.clear()
        self.comment_lines.clear()
        self.dirty = False
        self.exists = self.path.exists()
        if not self.exists:
            self.entries = {"ip": "127.0.0.1", "port": "30002", "client": DEFAULT_CLIENT}
            self.comment_lines = ["; CSNZ 启动器配置"]
            return

        raw = self.path.read_bytes()
        has_bom = raw.startswith(b"\xef\xbb\xbf")
        text = raw.decode("utf-8-sig", errors="replace")
        for line in text.splitlines():
            stripped = line.strip()
            if not stripped:
                continue
            if stripped.startswith(";") or stripped.startswith("#"):
                self.comment_lines.append(stripped)
                continue
            if "=" in stripped:
                k, v = stripped.split("=", 1)
                self.entries[k.strip()] = v.strip()
        self._has_bom = has_bom

    def save(self, backup_dir: Path | None = None) -> Path | None:
        backup = None
        if backup_dir:
            backup_dir.mkdir(parents=True, exist_ok=True)
            stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            backup = backup_dir / f"launcher_{stamp}.ini"
            if self.path.exists():
                shutil.copy2(self.path, backup)

        lines = list(self.comment_lines) or ["; CSNZ 启动器配置"]
        for key in ("ip", "port", "client"):
            if key in self.entries:
                lines.append(f"{key}={self.entries[key]}")
        # 保留任何额外键，避免丢配置
        for k, v in self.entries.items():
            if k not in ("ip", "port", "client"):
                lines.append(f"{k}={v}")

        body = "\r\n".join(lines) + "\r\n"
        self.path.write_text(BOM + body, encoding="utf-8", newline="")
        self.dirty = False
        self.exists = True
        return backup

    # ---- 字段 ----
    def get(self, key: str, default: str = "") -> str:
        return self.entries.get(key, default)

    def set(self, key: str, value: str) -> None:
        value = str(value).strip()
        if self.entries.get(key) != value:
            self.entries[key] = value
            self.dirty = True

    def validate(self) -> list[str]:
        problems: list[str] = []
        ip = self.get("ip")
        port = self.get("port")
        if not ip:
            problems.append("客户端连接 IP 不能为空")
        else:
            parts = ip.split(".")
            ok = len(parts) == 4 and all(
                p.isdigit() and 0 <= int(p) <= 255 for p in parts
            )
            if not ok and ip not in ("localhost",):
                problems.append(f"客户端连接 IP 格式不正确：{ip}（应形如 127.0.0.1 或 192.168.1.10）")
        if not port.isdigit() or not (1 <= int(port) <= 65535):
            problems.append(f"客户端连接端口非法：{port}（应为 1-65535）")
        return problems


def local_ipv4_addresses() -> list[str]:
    """列出本机局域网 IPv4，供填充到 launcher.ini 发给玩家。"""
    import socket
    out: list[str] = []
    try:
        # 连一个外部地址只为让系统选出默认出口网卡，不会真的发包
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.connect(("8.8.8.8", 80))
            out.append(s.getsockname()[0])
        finally:
            s.close()
    except OSError:
        pass
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ip = info[4][0]
            if ip not in out and not ip.startswith("127."):
                out.append(ip)
    except OSError:
        pass
    out.append("127.0.0.1")
    return out


__all__ = ["LauncherIni", "local_ipv4_addresses", "DEFAULT_CLIENT"]
