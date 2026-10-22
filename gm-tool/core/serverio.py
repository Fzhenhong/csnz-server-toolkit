"""服务端进程控制：启动 / stdin 下发控制台命令 / 日志监视。

CSNZ_Server.exe 是 CONSOLE 子系统程序，ReadConsoleThread 用 getline(cin) 收命令，
命令分发在 CServerInstance::OnCommand，因此 stdin 管道就是官方管理通道。

关于输出通道（实测结论）：
· stdout 一旦被重定向到管道就变成全缓冲（4KB），服务端不主动 flush，
  日志会卡在缓冲区里不吐出来，因此 stdout 只能用来确认进程存活，不能当实时日志。
· CFileLogger::LogVarg 是 fopen("a+") → vfprintf → fclose()，每条日志立即落盘，
  所以 Logs/Server_*.log 才是可靠的实时数据源。
本模块因此以文件日志为主，stdout 只做辅助。
"""
from __future__ import annotations

import re
import subprocess
import threading
from collections import deque
from datetime import datetime
from pathlib import Path
from typing import Callable

CREATE_NO_WINDOW = 0x08000000

LOG_LINE_RE = re.compile(r"^\[(?P<ts>[^\]]+)\]\s*\[(?P<level>[A-Z]+)\]\s*(?P<msg>.*)$")


class ServerProcess:
    """独占一个服务端子进程。工具关闭时应先 shutdown 再退出。"""

    def __init__(self) -> None:
        self.proc: subprocess.Popen | None = None
        self._lines: deque[str] = deque(maxlen=5000)
        self._lock = threading.Lock()
        self._reader: threading.Thread | None = None
        self._listeners: list[Callable[[str], None]] = []
        self._root: Path | None = None

        # ---- 进程守护 ----
        # 语义：只要进程不是「用户主动关闭」的，退出后就自动拉起。
        # 不使用服务端自带的 RestartOnCrash：那是崩溃时用 ShellExecute 拉一个
        # 分离进程，不接本工具的命令管道，会变成「工具管不到却占着端口」的孤儿。
        self.restart_delay = 5.0          # 退出后等待多久再拉起
        self.healthy_uptime = 30.0        # 活过这个时长才算一次正常启动
        self.max_restart_attempts = 20    # 连续快速失败的上限
        self._restart_attempts = 0
        self._stopping = False            # 用户主动关闭中
        self._restart_thread: threading.Thread | None = None
        self._started_at: float = 0.0
        self._on_state_change: list[Callable[[], None]] = []

    # ---- 状态 ----
    @property
    def running(self) -> bool:
        return self.proc is not None and self.proc.poll() is None

    @property
    def pid(self) -> int | None:
        return self.proc.pid if self.proc else None

    def lines(self) -> list[str]:
        with self._lock:
            return list(self._lines)

    def subscribe(self, fn: Callable[[str], None]) -> None:
        self._listeners.append(fn)

    # ---- 生命周期 ----
    def start(self, root: Path) -> tuple[bool, str]:
        if self.running:
            return False, "服务端已在运行"
        self._root = root
        self._stopping = False
        exe = root / "CSNZ_Server.exe"
        if not exe.exists():
            return False, f"找不到 {exe}"
        try:
            self.proc = subprocess.Popen(
                [str(exe)],
                cwd=str(root),
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                creationflags=CREATE_NO_WINDOW,
                bufsize=1,
            )
        except OSError as e:
            return False, f"启动失败：{e}"
        self._started_at = __import__("time").time()
        self._reader = threading.Thread(target=self._read_loop, daemon=True)
        self._reader.start()
        return True, f"已启动，PID {self.proc.pid}"

    def _read_loop(self) -> None:
        assert self.proc and self.proc.stdout
        for raw in iter(self.proc.stdout.readline, b""):
            line = raw.decode("gbk", errors="replace").rstrip()
            if not line:
                continue
            with self._lock:
                self._lines.append(line)
            for fn in self._listeners:
                try:
                    fn(line)
                except Exception:
                    pass
        code = self.proc.poll() if self.proc else None
        self._emit(f"--- 服务端进程已退出 (exit={code}) ---")
        self._notify_state()
        self._maybe_restart(code)

    def _emit(self, text: str) -> None:
        with self._lock:
            self._lines.append(text)
        for fn in self._listeners:
            try:
                fn(text)
            except Exception:
                pass

    # ---- 状态回调 ----
    def on_state_change(self, fn: Callable[[], None]) -> None:
        self._on_state_change.append(fn)

    def _notify_state(self) -> None:
        for fn in self._on_state_change:
            try:
                fn()
            except Exception:
                pass

    # ---- 进程守护 ----
    def set_restart_delay(self, delay: float) -> None:
        self.restart_delay = max(1.0, float(delay))

    def reset_restart_counter(self) -> None:
        self._restart_attempts = 0

    @property
    def guarding(self) -> bool:
        """正在守护：进程由本工具拉起且未处于主动关闭流程。"""
        return self._root is not None and not self._stopping

    def _maybe_restart(self, exit_code: int | None) -> None:
        """进程退出后的守护判断。

        规则只有两条：
        · 用户主动点了「关闭服务端」/「强制结束」 → 不再拉起；
        · 其余任何退出（崩溃、被外部杀掉、OOM…） → 等待后自动拉起。

        用「存活时长」而不是「启动成功」来清零失败计数：
        否则一个启动 2 秒就崩的服务端会被无限重拉，直到把机器拖死。
        """
        import time

        if self._stopping or self._root is None:
            self._emit("--- 已手动关闭，守护不重启 ---")
            return

        uptime = (time.time() - self._started_at) if self._started_at else 0.0
        if uptime >= self.healthy_uptime:
            # 稳定运行过一段时间才崩，视为偶发故障，重置计数
            self._restart_attempts = 0
        else:
            self._emit(f"--- 本次仅存活 {uptime:.0f} 秒，视为异常退出 ---")

        if self._restart_attempts >= self.max_restart_attempts:
            self._emit(
                f"--- 连续 {self._restart_attempts} 次异常退出，已停止守护，"
                f"请检查 Logs 目录与崩溃转储 (*.mdmp) ---"
            )
            return

        self._restart_attempts += 1
        self._emit(
            f"--- 服务端已掉线，{self.restart_delay:.0f} 秒后自动重启"
            f"（第 {self._restart_attempts}/{self.max_restart_attempts} 次）---"
        )
        self._restart_thread = threading.Thread(
            target=self._restart_after_delay, daemon=True
        )
        self._restart_thread.start()

    def _restart_after_delay(self) -> None:
        import time
        time.sleep(self.restart_delay)
        if self._stopping or self._root is None or self.running:
            return
        ok, msg = self.start(self._root)
        if ok:
            self._emit(f"--- 守护：服务端已重新启动（PID {self.pid}）---")
        else:
            self._emit(f"--- 守护：重启失败（{msg}），稍后重试 ---")
            # 启动本身就失败（如端口仍被占用），继续按退避重试
            if not self._stopping:
                self._maybe_restart(None)

    def send(self, command: str) -> tuple[bool, str]:
        if not self.running:
            return False, "服务端未运行"
        assert self.proc and self.proc.stdin
        command = command.strip()
        if not command:
            return False, "命令为空"
        try:
            self.proc.stdin.write((command + "\n").encode("gbk", errors="replace"))
            self.proc.stdin.flush()
        except (OSError, ValueError) as e:
            return False, f"写入失败：{e}"
        self._emit(f">> {command}")
        return True, "已发送"

    def stop(self, timeout: float = 15.0) -> tuple[bool, str]:
        if not self.running:
            return False, "服务端未运行"
        # 用户主动关闭：必须先置位，否则读循环看到退出会触发自动重启
        self._stopping = True
        # shutdown 会先给全服发维护公告再优雅关闭
        self.send("shutdown")
        assert self.proc
        try:
            self.proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            self.proc.kill()
            return True, "超时，已强制结束"
        return True, "已关闭"

    def kill(self) -> tuple[bool, str]:
        """强制结束，不等优雅关闭。用于服务端卡死、shutdown 无响应。"""
        if not self.running:
            return False, "服务端未运行"
        self._stopping = True
        assert self.proc
        try:
            self.proc.kill()
            self.proc.wait(timeout=5)
        except (OSError, subprocess.TimeoutExpired) as e:
            return False, f"结束失败：{e}"
        return True, "已强制结束"


class LogTail:
    """轮询 Logs 目录下本次运行产生的 Server_*.log。

    服务端每次启动都会新建一个带启动时间的日志文件，且每条日志都立即落盘
    （CFileLogger 用 fopen/fclose 逐条写），所以文件是唯一可靠的实时来源。

    为避免把历史日志混进来，绑定服务端时会记录启动时刻，
    只读取「修改时间不早于该时刻」的文件。
    """

    def __init__(self, logs_dir: Path) -> None:
        self.logs_dir = logs_dir
        self.path: Path | None = None
        self._pos = 0
        self._since: float | None = None

    def bind_start(self) -> None:
        """服务端启动后调用，之后只跟踪本次运行的日志文件。"""
        self._since = datetime.now().timestamp() - 5  # 容忍几秒时钟误差
        self.path = None
        self._pos = 0

    def latest(self) -> Path | None:
        if not self.logs_dir.exists():
            return None
        files = []
        for p in self.logs_dir.glob("Server_*.log"):
            try:
                mtime = p.stat().st_mtime
            except OSError:
                continue
            if self._since is None or mtime >= self._since:
                files.append((mtime, p))
        if not files:
            return None
        return max(files, key=lambda x: x[0])[1]

    def poll(self) -> list[str]:
        latest = self.latest()
        if latest is None:
            return []
        if latest != self.path:
            self.path = latest
            self._pos = 0
        try:
            size = latest.stat().st_size
        except OSError:
            return []
        if size < self._pos:
            self._pos = 0
        if size == self._pos:
            return []
        with latest.open("rb") as f:
            f.seek(self._pos)
            chunk = f.read()
            self._pos = f.tell()
        return chunk.decode("gbk", errors="replace").splitlines()

    @property
    def current_name(self) -> str:
        return self.path.name if self.path else "（等待本次运行的日志文件）"


def parse_log_line(line: str) -> tuple[str, str, str]:
    """返回 (时间, 级别, 内容)。非日志格式的行原样放回内容。"""
    m = LOG_LINE_RE.match(line)
    if not m:
        return "", "", line
    return m.group("ts"), m.group("level"), m.group("msg")


__all__ = ["ServerProcess", "LogTail", "parse_log_line", "CREATE_NO_WINDOW"]
