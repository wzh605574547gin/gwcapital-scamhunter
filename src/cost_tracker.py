"""日预算熔断 — 防止被刷爆 DeepSeek 余额。

线程安全。按自然日重置。服务重启会丢失计数(对 MVP 够用)。
以后流量大了换成 SQLite/Redis 持久化。
"""
from __future__ import annotations

import threading
from datetime import date

# DeepSeek V3 定价(2026,约算成 USD · 实际按人民币结算)
# 输入 ¥1/M  ≈ $0.14/M
# 输出 ¥8/M  ≈ $1.10/M
DEEPSEEK_INPUT_USD_PER_MTOKEN = 0.14
DEEPSEEK_OUTPUT_USD_PER_MTOKEN = 1.10


class CostTracker:
    def __init__(self, daily_budget_usd: float = 5.0):
        self.daily_budget_usd = daily_budget_usd
        self._today = date.today()
        self._today_spent_usd = 0.0
        self._today_requests = 0
        self._lock = threading.Lock()

    def _maybe_reset(self) -> None:
        if date.today() != self._today:
            self._today = date.today()
            self._today_spent_usd = 0.0
            self._today_requests = 0

    def has_budget(self) -> bool:
        with self._lock:
            self._maybe_reset()
            return self._today_spent_usd < self.daily_budget_usd

    def remaining_usd(self) -> float:
        with self._lock:
            self._maybe_reset()
            return max(0.0, self.daily_budget_usd - self._today_spent_usd)

    def record_usage(self, prompt_tokens: int, completion_tokens: int) -> float:
        """记录一次 LLM 调用的 token 消耗,返回累计今日花费。"""
        with self._lock:
            self._maybe_reset()
            cost = (
                (prompt_tokens / 1_000_000) * DEEPSEEK_INPUT_USD_PER_MTOKEN
                + (completion_tokens / 1_000_000) * DEEPSEEK_OUTPUT_USD_PER_MTOKEN
            )
            self._today_spent_usd += cost
            self._today_requests += 1
            return self._today_spent_usd

    def stats(self) -> dict:
        with self._lock:
            self._maybe_reset()
            return {
                "date": self._today.isoformat(),
                "spent_usd": round(self._today_spent_usd, 4),
                "budget_usd": self.daily_budget_usd,
                "remaining_usd": round(max(0.0, self.daily_budget_usd - self._today_spent_usd), 4),
                "requests": self._today_requests,
            }
