"""第三步端到端测试:命令行跑完整 Agent 循环。

用法:
    cd ~/Projects/tron-scam-agent
    uv run python -m tests.test_agent [TRON地址]

不带参数会用币安热钱包(应判定安全)。
每次 Agent 暂停时,终端会问 c/f/q,按回车继续。
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

from dotenv import load_dotenv

from src.agent import AgentEvent, run_cli

DEFAULT_ADDRESS = "TLa2f6VPqDgRE67v1736s7bJ8Ray5wYjU7"  # 币安热钱包


def _short_json(d: dict, maxlen: int = 200) -> str:
    import json
    s = json.dumps(d, ensure_ascii=False, default=str)
    return s if len(s) <= maxlen else s[:maxlen] + "…"


def print_event(ev: AgentEvent) -> None:
    t = ev.type
    d = ev.data
    if t == "thinking":
        text = (d.get("text") or "").strip()
        if text:
            print(f"\n💭 {text}")
    elif t == "tool_call":
        print(f"  → {d['name']}({_short_json(d['args'], 120)})")
    elif t == "tool_result":
        print(f"    ✓ {d['name']}: {_short_json(d['result'], 160)}")
    elif t == "phase_summary":
        print("\n" + "=" * 60)
        print(f"📊 阶段性结论  ({d['current_verdict']} / 置信度 {d['confidence']})")
        print("=" * 60)
        print(d["summary_markdown"])
        print("\n统计:", d["stats"])
    elif t == "final_report":
        print("\n" + "=" * 60)
        print("📄 最终报告")
        print("=" * 60)
        print(d.get("markdown", ""))
    elif t == "error":
        print(f"\n❌ 错误: {d.get('message')}")
    elif t == "done":
        print(f"\n✅ 结束:{d}")


def ask_user_decision(payload: dict) -> str:
    while True:
        choice = input("\n>>> 继续深挖(c) / 结束生成报告(f) / 退出(q): ").strip().lower()
        if choice in ("c", "f", "q"):
            return choice
        print("无效选项,请输入 c / f / q")


async def main() -> None:
    load_dotenv(Path(__file__).resolve().parents[1] / ".env")

    address = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_ADDRESS
    print(f"🎯 目标地址: {address}\n")

    await run_cli(address, decision_cb=ask_user_decision, on_event=print_event)


if __name__ == "__main__":
    asyncio.run(main())
