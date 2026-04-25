"""PyWebView JS Bridge — 前端通过 window.pywebview.api.* 调这里的方法。

对外接口:
- start_analysis(address)  启动 Agent,后台线程跑,事件通过 event_bus 推前端
- user_decision(choice)    唤醒暂停的 Agent,choice ∈ {continue, finish, quit}
- ping(text)               联通性握手(保留给首页做健康检查)
"""
from __future__ import annotations

import asyncio
import os
import re
import threading
from typing import Any

from src.agent import AGENT_API_KEY_ENV, Agent, AgentEvent
from src.event_bus import EventBus
from src.tron_client import TronClient, TronScanError

TRON_ADDRESS_RE = re.compile(r"^T[1-9A-HJ-NP-Za-km-z]{33}$")


class API:
    def __init__(self) -> None:
        self.window = None  # main.py 注入
        self._bus: EventBus | None = None

        # 后台 Agent 运行状态
        self._agent: Agent | None = None
        self._thread: threading.Thread | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._agent_task: asyncio.Task | None = None
        self._decision_queue: asyncio.Queue | None = None
        self._is_running = False
        self._awaiting_decision = False
        self._ending_reason: str | None = None

    # ================== JS Bridge 接口 ==================

    def ping(self, text: str = "") -> dict[str, Any]:
        return {"ok": True, "echo": text}

    def start_analysis(self, address: str, user_context: str = "") -> dict[str, Any]:
        address = (address or "").strip()
        if not TRON_ADDRESS_RE.match(address):
            return {"ok": False, "error": "TRON 地址格式不正确"}
        if self._is_running:
            return {"ok": False, "error": "已有分析在进行中"}
        config_error = self._validate_runtime_config()
        if config_error is not None:
            return {"ok": False, "error": config_error}

        user_context = (user_context or "").strip()[:2000]  # 防止用户粘贴海量文本

        self._ensure_bus()
        try:
            self._agent = Agent(address, user_context=user_context)
        except Exception:
            return {"ok": False, "error": "分析服务初始化失败，请检查 API 配置后重试"}
        self._is_running = True
        self._awaiting_decision = False
        self._ending_reason = None
        self._thread = threading.Thread(target=self._thread_body, daemon=True)
        self._thread.start()
        return {"ok": True, "address": address, "user_context": user_context}

    def user_decision(self, choice: str) -> dict[str, Any]:
        if choice not in ("continue", "finish", "quit"):
            return {"ok": False, "error": f"无效选项: {choice}"}
        if self._loop is None or self._decision_queue is None or not self._awaiting_decision:
            return {"ok": False, "error": "当前不在等待用户决策"}
        try:
            self._awaiting_decision = False
            self._loop.call_soon_threadsafe(self._decision_queue.put_nowait, choice)
        except RuntimeError as e:
            self._awaiting_decision = True
            return {"ok": False, "error": f"发送决策失败: {e}"}
        return {"ok": True}

    def cancel_analysis(self) -> dict[str, Any]:
        if not self._is_running:
            return {"ok": False, "error": "当前没有进行中的分析"}
        self._ending_reason = "user_cancelled"
        self._awaiting_decision = False
        if self._loop is None:
            return {"ok": False, "error": "分析任务尚未准备好，请稍后再试"}
        try:
            if self._decision_queue is not None:
                self._loop.call_soon_threadsafe(self._clear_pending_decisions)
            if self._agent_task is not None:
                self._loop.call_soon_threadsafe(self._agent_task.cancel)
            return {"ok": True}
        except RuntimeError:
            return {"ok": False, "error": "分析任务已结束，请重新开始"}

    # ================== 内部 ==================

    def _validate_runtime_config(self) -> str | None:
        missing_items: list[str] = []
        if not os.environ.get(AGENT_API_KEY_ENV, "").strip():
            missing_items.append("DeepSeek API Key")
        if not os.environ.get("TRON_PRO_API_KEY", "").strip():
            missing_items.append("TronScan API Key")
        if missing_items:
            return "未完成运行配置，请先补充：" + "、".join(missing_items)
        return None

    def _clear_pending_decisions(self) -> None:
        if self._decision_queue is None:
            return
        while True:
            try:
                self._decision_queue.get_nowait()
            except asyncio.QueueEmpty:
                break

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
        self._agent_task = self._loop.create_task(self._agent_loop())
        try:
            self._loop.run_until_complete(self._agent_task)
        except asyncio.CancelledError:
            reason = self._ending_reason or "cancelled"
            self._emit("session_end", {"reason": reason})
        except Exception as e:  # 防御:Agent 意外崩溃不能卡死线程
            self._emit("error", {"message": self._friendly_error_message(e)})
            self._emit("session_end", {"reason": "crashed"})
        finally:
            self._is_running = False
            self._awaiting_decision = False
            try:
                self._loop.close()
            except Exception:
                pass
            self._agent_task = None
            self._loop = None
            self._decision_queue = None
            self._thread = None
            self._ending_reason = None

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
                    self._clear_pending_decisions()
                    self._awaiting_decision = True
                    choice = await self._decision_queue.get()
                    self._awaiting_decision = False
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

    def _friendly_error_message(self, error: Exception) -> str:
        if isinstance(error, TronScanError):
            return "TronScan 服务不可用或配置有误，请检查 API Key 后重试"
        return "分析过程中发生异常，请稍后重试或检查配置"
