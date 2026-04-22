"""手动验证脚本——跑 6 个端点,看结果是否都能拿到。

用法:
    cd ~/Projects/tron-scam-agent
    uv run python -m tests.test_tron_client

需要 .env 里填好 TRON_PRO_API_KEY。
"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path

from dotenv import load_dotenv

from src.tron_client import TronClient

# 测试目标
USDT_CONTRACT = "TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t"  # USDT 合约
BINANCE_HOT = "TLa2f6VPqDgRE67v1736s7bJ8Ray5wYjU7"     # 币安热钱包


def _pretty(title: str, data) -> None:
    print(f"\n===== {title} =====")
    if isinstance(data, list):
        print(f"(list, {len(data)} items)  first 2:")
        data = data[:2]
    print(json.dumps(data, ensure_ascii=False, indent=2, default=str)[:1200])


async def main() -> None:
    load_dotenv(Path(__file__).resolve().parents[1] / ".env")

    async with TronClient() as client:
        # 1. accountv2 — USDT 合约
        info = await client.get_account_info(USDT_CONTRACT)
        _pretty("1. get_account_info(USDT 合约)", info)

        # 2. security_data — 币安热钱包(应该没风险标)
        sec = await client.get_security_data(BINANCE_HOT)
        _pretty("2. get_security_data(币安热钱包)", sec)

        # 3. transactions — 币安热钱包最近 5 笔 TRX
        txs = await client.get_transactions(BINANCE_HOT, limit=5)
        _pretty("3. get_transactions(币安热钱包, 5 笔)", txs)

        # 4. trc20 transfers — 币安热钱包最近 5 笔
        trc20 = await client.get_trc20_transfers(BINANCE_HOT, limit=5)
        _pretty("4. get_trc20_transfers(币安热钱包, 5 笔)", trc20)

        # 5. token_security — USDT 合约(应该 token_level 高)
        tok_sec = await client.get_token_security(USDT_CONTRACT)
        _pretty("5. get_token_security(USDT)", tok_sec)

        # 6. account_tokens — 币安热钱包
        tokens = await client.get_account_tokens(BINANCE_HOT)
        _pretty("6. get_account_tokens(币安热钱包)", tokens)

    print("\n✅ 6 个端点全部调通")


if __name__ == "__main__":
    asyncio.run(main())
