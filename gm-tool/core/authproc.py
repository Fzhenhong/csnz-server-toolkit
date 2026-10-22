"""鉴权服务进程托管。

把 AuthServer 作为一个普通子进程管理，和 CSNZ 服务端并列，
这样操作员只开一个管理工具，不用再单独开 cmd 窗口。

设计要点：

1. 用子进程 + 管道，而不是 shell 启动，才能拿到日志、干净地停止。
2. 就绪判定看端口是否在监听，而不是「进程起来了」——
   uvicorn 启动到能响应有几百毫秒延迟，提前放行会让登录器偶发连不上。
3. 停止时先 terminate，超时再 kill，避免留下占端口的孤儿进程。
4. 鉴权服务必须同样被守护：它挂了意味着全服玩家都无法登录，
   比游戏服务端挂掉更隐蔽——玩家只会看到「连不上登录服务器」。
   守护规则与 ServerProcess 一致：非手动停止的退出都自动拉起。

为什么鉴权服务特别需要守护：它只是个单进程 uvicorn，
Python 层任何未捕获异常都可能让进程退出。没有守护时，
管理员必须自己发现并手动重启，中间这段时间新玩家进不来。
"""
from __future__ import annotations

import socket
import subprocess
import sys
import threading
import time
from collections import deque
from pathlib import Path
from typing import Callable

CREATE_NO_WINDOW = 0x08000000


def port_open(host: str, port: int, timeout: float = 0.6) -> bool:
    """检测端口是否已在监听。"""
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


class AuthServerProcess:
    """管理 AuthServer/server.py 的生命周期，含崩溃自动重启。"""

    def __init__(self) -> None:
        self.proc: subprocess.Popen | None = None
        self.host = "127.0.0.1"
        self.port = 38120
        self.script: Path | None = None
        self._lines: deque[str] = deque(maxlen=2000)
        self._lock = threading.Lock()
        self._reader: threading.Thread | None = None
        self._listeners: list[Callable[[str], None]] = []

        # ---- 守护 ----
        self.restart_delay = 5.0        # 退出后等待多久再拉起
        self.healthy_uptime = 30.0      # 活过这个时长才视为一次正常启动
        self.max_restart_attempts = 20  # 连续快速失败上限
        self._restart_attempts = 0
        self._stopping = False          # 用户主动停止中
        self._started_at: float = 0.0
        self._restart_thread: threading.Thread | None = None

    # ---- 状态 ----
    @property
    def running(self) -> bool:
        return self.proc is not None and self.proc.poll() is None

    @property
    def pid(self) -> int | None:
        return self.proc.pid if self.proc else None

    @property
    def ready(self) -> bool:
        """端口可连才算真正可用。进程活着但端口没通只是启动中。"""
        return self.running and port_open(self.host, self.port)

    def lines(self) -> list[str]:
        with self._lock:
            return list(self._lines)

    def subscribe(self, fn: Callable[[str], None]) -> None:
        self._listeners.append(fn)

    def _emit(self, text: str) -> None:
        with self._lock:
            self._lines.append(text)
        for fn in self._listeners:
            try:
                fn(text)
            except Exception:
                pass

    # ---- 生命周期 ----
    def configure(self, script: Path, host: str = "127.0.0.1",
                  port: int = 38120) -> None:
        self.script = script
        self.host = host or "127.0.0.1"
        self.port = int(port)

    def start(self, wait_ready: float = 12.0) -> tuple[bool, str]:
        if self.running:
            return False, "鉴权服务已在运行"
        if not self.script or not self.script.exists():
            return False, f"找不到鉴权服务脚本：{self.script}"

        self._stopping = False

        # 端口已被别人占用：可能是上次遗留的进程，直接复用而不是再起一个。
        # 此时没有本进程句柄，记下开始时间让守护算存活时长时有依据。
        if port_open(self.host, self.port):
            self._started_at = time.time()
            return True, f"端口 {self.port} 已有服务在监听，直接复用"

        try:
            self.proc = subprocess.Popen(
                [sys.executable, str(self.script.name)],
                cwd=str(self.script.parent),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                creationflags=CREATE_NO_WINDOW,
                bufsize=1,
            )
        except OSError as e:
            return False, f"启动失败：{e}"

        # 记录启动时刻：守护用它计算存活时长，判断是偶发崩溃还是崩溃循环
        self._started_at = time.time()

        self._reader = threading.Thread(target=self._read_loop, daemon=True)
        self._reader.start()

        # 等端口真正可连接，而不是只看进程活着
        deadline = time.time() + wait_ready
        while time.time() < deadline:
            if self.proc.poll() is not None:
                return False, "鉴权服务启动后立即退出，请查看日志"
            if port_open(self.host, self.port):
                return True, f"已启动，PID {self.proc.pid}"
            time.sleep(0.25)
        return False, f"启动超时（{wait_ready:.0f} 秒内端口 {self.port} 未就绪）"

    def _read_loop(self) -> None:
        assert self.proc and self.proc.stdout
        for raw in iter(self.proc.stdout.readline, b""):
            line = raw.decode("utf-8", "replace").rstrip()
            if line:
                self._emit(line)
        self._emit("--- 鉴权服务已退出 ---")
        # 退出后交给守护判断；手动停止时 _stopping 已置位，不会拉起
        self._maybe_restart()

    # ---- 守护 ----
    @property
    def guarding(self) -> bool:
        """正在守护：进程由本工具拉起且未处于主动停止流程。"""
        return self.script is not None and not self._stopping

    def set_restart_delay(self, delay: float) -> None:
        self.restart_delay = max(1.0, float(delay))

    def reset_restart_counter(self) -> None:
        self._restart_attempts = 0

    def _maybe_restart(self) -> None:
        """鉴权服务退出后的守护判断。

        规则与游戏服务端一致：
          · 用户主动点「停止鉴权」 → 不再拉起
          · 其余任何退出（崩溃/被杀/OOM） → 等待后自动拉起

        用「存活时长」而不是「启动成功」清零计数，
        否则一个起来就崩的进程会被无限重拉。
        """
        if self._stopping or self.script is None:
            self._emit("--- 已手动停止，守护不重启 ---")
            return

        uptime = (time.time() - self._started_at) if self._started_at else 0.0
        if uptime >= self.healthy_uptime:
            self._restart_attempts = 0
        else:
            self._emit(f"--- 本次仅存活 {uptime:.0f} 秒，视为异常退出 ---")

        if self._restart_attempts >= self.max_restart_attempts:
            self._emit(
                f"--- 连续 {self._restart_attempts} 次异常退出，已停止守护，"
                f"请检查鉴权服务日志 ---"
            )
            return

        self._restart_attempts += 1
        self._emit(
            f"--- 鉴权服务已掉线，{self.restart_delay:.0f} 秒后自动重启"
            f"（第 {self._restart_attempts}/{self.max_restart_attempts} 次）---"
        )
        self._restart_thread = threading.Thread(
            target=self._restart_after_delay, daemon=True)
        self._restart_thread.start()

    def _restart_after_delay(self) -> None:
        time.sleep(self.restart_delay)
        if self._stopping or self.script is None or self.running:
            return
        ok, msg = self.start()
        if ok:
            self._emit(f"--- 守护：鉴权服务已重新启动（PID {self.pid}）---")
        else:
            self._emit(f"--- 守护：鉴权重启失败（{msg}），稍后重试 ---")
            if not self._stopping:
                self._maybe_restart()

    def stop(self, timeout: float = 8.0) -> tuple[bool, str]:
        if not self.running:
            return False, "鉴权服务未运行"
        # 用户主动停止：必须先置位，否则读循环看到退出会触发自动重启
        self._stopping = True
        assert self.proc
        try:
            self.proc.terminate()
            self.proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            self.proc.kill()
            try:
                self.proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                return False, "无法结束进程"
            return True, "已强制结束"
        except OSError as e:
            return False, f"结束失败：{e}"
        return True, "已停止"


__all__ = ["AuthServerProcess", "port_open"]
