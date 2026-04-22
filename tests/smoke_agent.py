"""非交互 smoke test:跑到第一个暂停 → 自动选"结束生成报告" → 打印结果。

用于自动验证 Agent 循环功能,不需要人工输入。
"""
from __future__ import annotations

import asyncio
import sys
import time
from pathlib import Path

from dotenv import load_dotenv

from src.agent import Agent
from src.tron_client import TronClient
from tests.test_agent import DEFAULT_ADDRESS, print_event


async def main() -> None:
    load_dotenv(Path(__file__).resolve().parents[1] / ".env")

    address = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_ADDRESS
    print(f"🎯 目标地址: {address}")
    print(f"📋 策略:跑到第一个 phase_summary → 自动选 finish → 看最终报告\n")

    t0 = time.time()
    agent = Agent(address)
    async with TronClient() as client:
        ev1 = await agent.run_until_pause_or_end(client, on_event=print_event)
        print(f"\n--- 第一轮结束,type={ev1.type},耗时 {time.time()-t0:.1f}s ---")

        if ev1.type == "phase_summary":
            agent.resume_finish()
            ev2 = await agent.run_until_pause_or_end(client, on_event=print_event)
            print(f"\n--- 第二轮结束,type={ev2.type},总耗时 {time.time()-t0:.1f}s ---")
        elif ev1.type == "final_report":
            print("\n(Agent 直接给出最终结论,未触发暂停)")
        else:
            print(f"\n(意外事件类型:{ev1.type})")

    print(f"\n最终 graph 统计: {agent.graph.stats()}")


if __name__ == "__main__":
    asyncio.run(main())
