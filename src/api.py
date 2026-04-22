"""PyWebView JS Bridge — 前端通过 window.pywebview.api.* 调这里的方法。

对外接口:
- start_analysis(address)  启动 Agent,后台线程跑,事件通过 event_bus 推前端
- user_decision(choice)    唤醒暂停的 Agent,choice ∈ {continue, finish, quit}
- ping(text)               联通性握手(保留给首页做健康检查)
"""
from __future__ import annotations

import asyncio
import re
import threading
from typing import Any

from src.agent import Agent, AgentEvent
from src.event_bus import EventBus
from src.tron_client import TronClient

TRON_ADDRESS_RE = re.compile(r"^T[1-9A-HJ-NP-Za-km-z]{33}$")


class API:
    def __init__(self) -> None:
        self.window = None  # main.py 注入
        self._bus: EventBus | None = None

        # 后台 Agent 运行状态
        self._agent: Agent | None = None
        self._thread: threading.Thread | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._decision_queue: asyncio.Queue | None = None
        self._is_running = False

    # ================== JS Bridge 接口 ==================

    def ping(self, text: str = "") -> dict[str, Any]:
        return {"ok": True, "echo": text}

    def start_analysis(self, address: str, user_context: str = "") -> dict[str, Any]:
        address = (address or "").strip()
        if not TRON_ADDRESS_RE.match(address):
            return {"ok": False, "error": "TRON 地址格式不正确"}
        if self._is_running:
            return {"ok": False, "error": "已有分析在进行中"}

        user_context = (user_context or "").strip()[:2000]  # 防止用户粘贴海量文本

        self._ensure_bus()
        self._agent = Agent(address, user_context=user_context)
        self._is_running = True
        self._thread = threading.Thread(target=self._thread_body, daemon=True)
        self._thread.start()
        return {"ok": True, "address": address, "user_context": user_context}

    def user_decision(self, choice: str) -> dict[str, Any]:
        if choice not in ("continue", "finish", "quit"):
            return {"ok": False, "error": f"无效选项: {choice}"}
        if self._loop is None or self._decision_queue is None:
            return {"ok": False, "error": "当前没有等待决策"}
        try:
            self._loop.call_soon_threadsafe(self._decision_queue.put_nowait, choice)
        except RuntimeError as e:
            return {"ok": False, "error": f"发送决策失败: {e}"}
        return {"ok": True}

    # ================== 内部 ==================

    def _ensure_bus(self) -> None:
        if self._bus is None and self.window is not None:
            self._bus = EventBus(self.window)

    def _emit(self, type_: str, data: dict[str, Any] | None = None) -> None:
        if self._bus is None:
            return
        self._bus.emit(type_, data or {})

    def _thread_body(self) -> None:
        """后台线程入口:新建事件循环,跑 agent 主协程。"""
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        self._decision_queue = asyncio.Queue()
        try:
            self._loop.run_until_complete(self._agent_loop())
        except Exception as e:  # 防御:Agent 意外崩溃不能卡死线程
            self._emit("error", {"message": f"Agent 崩溃: {e!r}"})
            self._emit("session_end", {"reason": "crashed"})
        finally:
            self._is_running = False
            try:
                self._loop.close()
            except Exception:
                pass
            self._loop = None
            self._decision_queue = None

    async def _agent_loop(self) -> None:
        assert self._agent is not None
        self._emit("session_start", {"address": self._agent.target})

        async with TronClient() as client:
            while True:
                ev = await self._agent.run_until_pause_or_end(
                    client, on_event=self._forward_agent_event
                )
                # 阶段结束后给前端最新快照
                self._emit("graph_snapshot", self._agent.graph.snapshot())

                if ev.type == "phase_summary":
                    assert self._decision_queue is not None
                    choice = await self._decision_queue.get()
                    if choice == "continue":
                        self._agent.resume_continue()
                        continue
                    if choice == "finish":
                        self._agent.resume_finish()
                        continue
                    self._emit("session_end", {"reason": "user_quit"})
                    return

                # final_report / done / error —— 任务结束
                self._emit("session_end", {"reason": ev.type, "data": ev.data})
                return

    def _forward_agent_event(self, ev: AgentEvent) -> None:
        """Agent 事件 → 前端。中途关键事件后补一次 graph_snapshot。"""
        self._emit(ev.type, ev.data)
        if ev.type == "tool_result":
            name = ev.data.get("name")
            if name in {
                "analyze_address",
                "get_address_transactions",
                "mark_branch_complete",
                "record_finding",
            }:
                assert self._agent is not None
                self._emit("graph_snapshot", self._agent.graph.snapshot())
