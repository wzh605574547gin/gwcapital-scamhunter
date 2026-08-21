"""按 IP 限流 + 黑名单 — 防止单一 IP 刷爆服务。

策略:
- 每个 IP 每自然日最多 N 次分析
- 黑名单列表(环境变量 BLOCKED_IPS 逗号分隔)直接拒绝
- 内存存储(重启清空 · MVP 够用)
"""
from __future__ import annotations

import os
import threading
from collections import defaultdict
from datetime import date


class RateLimiter:
    def __init__(self, daily_limit_per_ip: int = 3):
        self.daily_limit_per_ip = daily_limit_per_ip
        self._today = date.today()
        self._counts: dict[str, int] = defaultdict(int)
        self._lock = threading.Lock()
        blocked = os.environ.get("BLOCKED_IPS", "")
        self._blocklist: set[str] = {ip.strip() for ip in blocked.split(",") if ip.strip()}

    def _maybe_reset(self) -> None:
        if date.today() != self._today:
            self._today = date.today()
            self._counts.clear()

    def is_blocked(self, ip: str) -> bool:
        return ip in self._blocklist

    def try_consume(self, ip: str) -> tuple[bool, int, int]:
        """(allowed, used_today, limit)"""
        if self.is_blocked(ip):
            return False, 0, self.daily_limit_per_ip
        with self._lock:
            self._maybe_reset()
            used = self._counts[ip]
            if used >= self.daily_limit_per_ip:
                return False, used, self.daily_limit_per_ip
            self._counts[ip] += 1
            return True, self._counts[ip], self.daily_limit_per_ip

    def remaining(self, ip: str) -> int:
        with self._lock:
            self._maybe_reset()
            return max(0, self.daily_limit_per_ip - self._counts[ip])
