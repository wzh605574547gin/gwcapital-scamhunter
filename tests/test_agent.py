from __future__ import annotations

import asyncio
import os
import sys
import types
import unittest
from unittest.mock import patch

if "openai" not in sys.modules:
    fake_openai = types.ModuleType("openai")

    class _AsyncOpenAI:  # pragma: no cover - test import stub
        def __init__(self, *args, **kwargs) -> None:
            pass

    fake_openai.AsyncOpenAI = _AsyncOpenAI
    sys.modules["openai"] = fake_openai

if "httpx" not in sys.modules:
    fake_httpx = types.ModuleType("httpx")

    class _AsyncClient:  # pragma: no cover - test import stub
        def __init__(self, *args, **kwargs) -> None:
            pass

        async def aclose(self) -> None:
            return None

    fake_httpx.AsyncClient = _AsyncClient
    sys.modules["httpx"] = fake_httpx

if "tenacity" not in sys.modules:
    fake_tenacity = types.ModuleType("tenacity")

    def _retry(*args, **kwargs):
        def decorator(func):
            return func
        return decorator

    def _identity(*args, **kwargs):
        return None

    fake_tenacity.retry = _retry
    fake_tenacity.retry_if_exception_type = _identity
    fake_tenacity.stop_after_attempt = _identity
    fake_tenacity.wait_exponential = _identity
    sys.modules["tenacity"] = fake_tenacity

from src.api import API
from src.tron_client import TronScanError


class DummyAgent:
    def __init__(self, target_address: str, user_context: str = "") -> None:
        self.target = target_address
        self.user_context = user_context


class ApiTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.api = API()
        self.valid_address = "TLa2f6VPqDgRE67v1736s7bJ8Ray5wYjU7"

    def test_start_analysis_requires_config_before_thread_starts(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            result = self.api.start_analysis(self.valid_address)

        self.assertEqual(
            result,
            {
                "ok": False,
                "error": "未完成运行配置，请先补充：DeepSeek API Key、TronScan API Key",
            },
        )
        self.assertFalse(self.api._is_running)
        self.assertIsNone(self.api._thread)

    def test_start_analysis_trims_context_and_starts_thread(self) -> None:
        with (
            patch.dict(
                os.environ,
                {"DEEPSEEK_API_KEY": "deepseek", "TRON_PRO_API_KEY": "tron"},
                clear=True,
            ),
            patch("src.api.Agent", DummyAgent),
            patch.object(API, "_thread_body", autospec=True),
        ):
            result = self.api.start_analysis(self.valid_address, " x " * 800)

        self.assertTrue(result["ok"])
        self.assertLessEqual(len(result["user_context"]), 2000)
        self.assertTrue(self.api._is_running)
        self.assertIsNotNone(self.api._thread)

    def test_user_decision_rejected_when_not_waiting(self) -> None:
        self.api._loop = asyncio.new_event_loop()
        self.api._decision_queue = asyncio.Queue()
        self.api._awaiting_decision = False
        try:
            result = self.api.user_decision("finish")
        finally:
            self.api._loop.close()
            self.api._loop = None
            self.api._decision_queue = None

        self.assertEqual(result, {"ok": False, "error": "当前不在等待用户决策"})

    def test_user_decision_accepts_when_waiting(self) -> None:
        loop = asyncio.new_event_loop()
        queue: asyncio.Queue[str] = asyncio.Queue()
        captured: list[str] = []

        def call_soon_threadsafe(callback, *args):
            callback(*args)

        async def drain() -> None:
            captured.append(await queue.get())

        self.api._loop = loop
        self.api._decision_queue = queue
        self.api._awaiting_decision = True
        with patch.object(loop, "call_soon_threadsafe", side_effect=call_soon_threadsafe):
            result = self.api.user_decision("finish")
            loop.run_until_complete(drain())
        loop.close()
        self.api._loop = None
        self.api._decision_queue = None

        self.assertEqual(result, {"ok": True})
        self.assertEqual(captured, ["finish"])
        self.assertFalse(self.api._awaiting_decision)

    def test_cancel_analysis_requires_running_session(self) -> None:
        result = self.api.cancel_analysis()
        self.assertEqual(result, {"ok": False, "error": "当前没有进行中的分析"})

    def test_cancel_analysis_cancels_task_and_clears_waiting_state(self) -> None:
        loop = asyncio.new_event_loop()
        task = loop.create_task(asyncio.sleep(60))
        queue: asyncio.Queue[str] = asyncio.Queue()
        queue.put_nowait("continue")

        def call_soon_threadsafe(callback, *args):
            callback(*args)

        self.api._is_running = True
        self.api._loop = loop
        self.api._agent_task = task
        self.api._decision_queue = queue
        self.api._awaiting_decision = True

        with patch.object(loop, "call_soon_threadsafe", side_effect=call_soon_threadsafe):
            result = self.api.cancel_analysis()
        try:
            loop.run_until_complete(task)
        except asyncio.CancelledError:
            pass

        self.assertEqual(result, {"ok": True})
        self.assertEqual(self.api._ending_reason, "user_cancelled")
        self.assertFalse(self.api._awaiting_decision)
        self.assertTrue(task.cancelled())
        self.assertTrue(queue.empty())

        loop.close()
        self.api._loop = None
        self.api._agent_task = None
        self.api._decision_queue = None
        self.api._is_running = False

    def test_friendly_error_message_hides_internal_details(self) -> None:
        msg = self.api._friendly_error_message(TronScanError("TRON_PRO_API_KEY missing"))
        self.assertEqual(msg, "TronScan 服务不可用或配置有误，请检查 API Key 后重试")


if __name__ == "__main__":
    unittest.main()
