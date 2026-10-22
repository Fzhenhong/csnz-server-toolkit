"""登录限频，防暴力破解。

设计取舍：

· 用「滑动窗口 + 失败计数」，不是固定窗口。固定窗口在边界处会被双倍刷。
· 成功登录立刻清空该用户的失败计数，正常玩家永远不会被自己的重试锁住。
· IP 与账号两个维度分别计数：攻击者换账号刷同一 IP 会被 IP 维度拦，
  换 IP 刷同一账号会被账号维度拦。
· 命中限制后进入冷却期，冷却期内直接拒绝，不再累加（避免计数无限增长）。
· 全部在内存里，进程重启即清空——这是刻意的：宁可重启后放宽，
  也不要让一个 bug 把整服人永久锁死。
"""
from __future__ import annotations

import threading
import time
from collections import defaultdict, deque


class RateLimiter:
    """按 key 统计失败次数，超阈值后进入冷却期。"""

    def __init__(self, max_fails: int = 5, window: float = 600.0,
                 cooldown: float = 600.0) -> None:
        self.max_fails = max_fails
        self.window = window
        self.cooldown = cooldown
        self._fails: dict[str, deque[float]] = defaultdict(deque)
        self._blocked_until: dict[str, float] = {}
        self._cumulative: dict[str, int] = defaultdict(int)   # 累计失败，不清零
        self._lock = threading.Lock()

    # ---- 内部 ----
    def _prune(self, key: str, now: float) -> deque[float]:
        q = self._fails[key]
        while q and now - q[0] > self.window:
            q.popleft()
        return q

    # ---- 对外 ----
    def check(self, key: str) -> float:
        """返回剩余冷却秒数；0 表示放行。"""
        with self._lock:
            now = time.time()
            until = self._blocked_until.get(key, 0.0)
            if until > now:
                return until - now
            if until:
                # 冷却结束，清掉记录重新计
                self._blocked_until.pop(key, None)
                self._fails.pop(key, None)
            return 0.0

    def fail(self, key: str) -> float:
        """记一次失败。若达阈值则返回冷却秒数，否则返回 0。"""
        with self._lock:
            now = time.time()
            q = self._prune(key, now)
            q.append(now)
            self._cumulative[key] += 1
            if len(q) >= self.max_fails:
                self._blocked_until[key] = now + self.cooldown
                q.clear()
                return self.cooldown
            return 0.0

    def success(self, key: str) -> None:
        """登录成功：清空该 key 的失败记录。"""
        with self._lock:
            self._fails.pop(key, None)
            self._blocked_until.pop(key, None)

    def remaining_fails(self, key: str) -> int:
        with self._lock:
            now = time.time()
            return max(0, self.max_fails - len(self._prune(key, now)))

    def total_fails(self, key: str) -> int:
        """该 key 在窗口内的失败总次数（含已触发限频后清零前的次数）。

        单独维护，因为 _fails 在触发冷却时会被清空，
        而自动封禁需要知道「这个人一共试了多少次」。
        """
        with self._lock:
            return self._cumulative.get(key, 0)

    def snapshot(self) -> dict[str, int]:
        """当前处于冷却中的 key 及剩余秒数，供运维查看。"""
        with self._lock:
            now = time.time()
            return {
                k: int(v - now) for k, v in self._blocked_until.items() if v > now
            }


__all__ = ["RateLimiter"]
