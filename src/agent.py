"""Agent 主循环——让 LLM 自主规划、调工具、阶段性暂停。

使用 OpenAI 兼容 API(DeepSeek / Qwen / Kimi 等均可)。
模型切换改 AGENT_MODEL 和 AGENT_BASE_URL 两个常量即可。
"""
from __future__ import annotations

import asyncio
import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, AsyncIterator, Callable

from openai import AsyncOpenAI

from src.memory.graph import AddressGraph
from src.tools.definitions import TOOL_DEFINITIONS
from src.tools.executors import ToolContext, execute
from src.tron_client import TronClient

# ---------- 可切换的模型配置 ----------
AGENT_MODEL = os.environ.get("AGENT_MODEL", "deepseek-chat")
AGENT_BASE_URL = os.environ.get("AGENT_BASE_URL", "https://api.deepseek.com")
AGENT_API_KEY_ENV = os.environ.get("AGENT_API_KEY_ENV", "DEEPSEEK_API_KEY")

# ---------- 硬性限制 ----------
MAX_TOTAL_TOOL_CALLS = 30          # 整个任务的硬上限
MAX_PHASE_TOOL_CALLS = 10          # 单阶段软上限,超了强制提醒 LLM 暂停
MAX_ROUNDS = 50                    # LLM 调用轮次硬上限

SYSTEM_PROMPT_PATH = Path(__file__).resolve().parent / "prompts" / "system.md"


# ---------- 事件类型 ----------

@dataclass
class AgentEvent:
    """Agent 运行时产生的事件,供外层(CLI/UI)消费。"""
    type: str  # thinking / tool_call / tool_result / phase_summary / final_report / error / done
    data: dict[str, Any] = field(default_factory=dict)


# ---------- Agent 核心 ----------

class Agent:
    def __init__(self, target_address: str, user_context: str = ""):
        self.target = target_address
        self.user_context = (user_context or "").strip()
        self.graph = AddressGraph(target_address)
        self.messages: list[dict[str, Any]] = []
        self.total_tool_calls = 0
        self.phase_tool_calls = 0
        self.round = 0
        self._paused_payload: dict[str, Any] | None = None

        self._load_system_prompt()

        api_key = os.environ.get(AGENT_API_KEY_ENV, "").strip()
        if not api_key:
            raise RuntimeError(f"{AGENT_API_KEY_ENV} 未设置")
        self.llm = AsyncOpenAI(api_key=api_key, base_url=AGENT_BASE_URL)

    def _load_system_prompt(self) -> None:
        sys_prompt = SYSTEM_PROMPT_PATH.read_text(encoding="utf-8")
        self.messages.append({"role": "system", "content": sys_prompt})

        user_msg = f"请分析这个 TRON 地址,追溯它的资金流向与风险状态:\n\n**{self.target}**"
        if self.user_context:
            user_msg += (
                "\n\n---\n## 用户提供的背景信息\n\n"
                f"{self.user_context}\n\n---\n\n"
                "请把用户这段话作为**重要线索**:用链上数据去验证或反驳其中的说法,"
                "指出哪些能被数据证实、哪些与链上事实不符、哪些暂时无法判断。"
                "你的阶段性结论和最终报告里都要体现对用户信息的回应。"
            )
        self.messages.append({"role": "user", "content": user_msg})

    # ---------- 外层控制(CLI 或 UI 调用) ----------

    async def run_until_pause_or_end(
        self,
        tron_client: TronClient,
        on_event: Callable[[AgentEvent], Any] | None = None,
    ) -> AgentEvent:
        """跑到下一次暂停(调 request_user_decision)或任务结束。"""
        ctx = ToolContext(client=tron_client, graph=self.graph)
        emit = on_event or (lambda _e: None)

        while self.round < MAX_ROUNDS and self.total_tool_calls < MAX_TOTAL_TOOL_CALLS:
            self.round += 1

            # 阶段内超限,强塞一条系统提醒让 LLM 暂停
            if self.phase_tool_calls >= MAX_PHASE_TOOL_CALLS:
                self.messages.append(
                    {
                        "role": "user",
                        "content": "【系统提示】本阶段工具调用已超过上限,请立即调用 request_user_decision 总结当前进展并请求用户决策。",
                    }
                )
                self.phase_tool_calls = 0

            # 调 LLM
            try:
                resp = await self.llm.chat.completions.create(
                    model=AGENT_MODEL,
                    messages=self.messages,
                    tools=TOOL_DEFINITIONS,
                    tool_choice="auto",
                    temperature=0.3,
                )
            except Exception as e:
                ev = AgentEvent(type="error", data={"message": str(e)})
                emit(ev)
                return ev

            msg = resp.choices[0].message
            # 把 assistant 消息加入历史(包括可能的 tool_calls)
            assistant_msg: dict[str, Any] = {"role": "assistant"}
            if msg.content:
                assistant_msg["content"] = msg.content
                emit(AgentEvent(type="thinking", data={"text": msg.content}))
            else:
                assistant_msg["content"] = None

            tool_calls = msg.tool_calls or []
            if tool_calls:
                assistant_msg["tool_calls"] = [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {"name": tc.function.name, "arguments": tc.function.arguments},
                    }
                    for tc in tool_calls
                ]
            self.messages.append(assistant_msg)

            # 没有工具调用——LLM 直接回文本,大概率是最终报告或需要用户输入
            if not tool_calls:
                ev = AgentEvent(type="final_report", data={"markdown": msg.content or ""})
                emit(ev)
                return ev

            # 逐个执行工具
            for tc in tool_calls:
                try:
                    args = json.loads(tc.function.arguments or "{}")
                except json.JSONDecodeError:
                    args = {}
                emit(AgentEvent(type="tool_call", data={"name": tc.function.name, "args": args}))

                result = await execute(ctx, tc.function.name, args)
                self.total_tool_calls += 1
                self.phase_tool_calls += 1

                emit(AgentEvent(type="tool_result", data={"name": tc.function.name, "result": result}))

                self.messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": json.dumps(result, ensure_ascii=False, default=str),
                    }
                )

                # 命中 request_user_decision 的暂停信号
                if isinstance(result, dict) and result.get("__paused__"):
                    self._paused_payload = {
                        "current_verdict": result["current_verdict"],
                        "confidence": result["confidence"],
                        "summary_markdown": result["summary_markdown"],
                        "suggested_next_steps": result.get("suggested_next_steps", []),
                        "stats": self.graph.stats(),
                    }
                    ev = AgentEvent(type="phase_summary", data=self._paused_payload)
                    emit(ev)
                    self.phase_tool_calls = 0
                    return ev

        # 外层循环超限
        ev = AgentEvent(
            type="done",
            data={"reason": "hit_max_limit", "stats": self.graph.stats()},
        )
        emit(ev)
        return ev

    def resume_continue(self) -> None:
        """用户选"继续深挖",注入新的 user 消息让 LLM 接着做。"""
        self.messages.append(
            {
                "role": "user",
                "content": "用户选择**继续深挖**。请基于目前已知信息,推进到下一个分析阶段,完成后再次调用 request_user_decision。",
            }
        )

    def resume_finish(self) -> None:
        """用户选"结束生成报告",让 LLM 产出最终 Markdown 报告。"""
        self.messages.append(
            {
                "role": "user",
                "content": (
                    "用户选择**结束并生成最终报告**。"
                    "请严格按 system prompt 中定义的最终报告 Markdown 结构输出完整报告。"
                    "**不要再调用任何工具**——直接以 assistant 文本形式返回 Markdown。"
                ),
            }
        )


# ---------- 便捷入口:跑完整流程,支持暂停交互 ----------

async def run_cli(
    target_address: str,
    decision_cb: Callable[[dict[str, Any]], str],
    on_event: Callable[[AgentEvent], Any] | None = None,
) -> AgentEvent | None:
    """命令行流程:每次 phase_summary 触发 decision_cb 拿决定(c/f/q)。"""
    agent = Agent(target_address)
    async with TronClient() as client:
        while True:
            ev = await agent.run_until_pause_or_end(client, on_event=on_event)
            if ev.type == "phase_summary":
                choice = decision_cb(ev.data)
                if choice == "c":
                    agent.resume_continue()
                    continue
                if choice == "f":
                    agent.resume_finish()
                    continue
                return ev  # q / quit
            return ev
