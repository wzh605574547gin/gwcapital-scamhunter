"""FastAPI 服务器 — Web 部署入口。

架构:
  浏览器(前端) ←── wss ──→ FastAPI(本模块) ←── async ──→ Agent ←── https ──→ DeepSeek / TronScan

对外暴露:
  GET  /healthz                Fly 健康检查
  GET  /api/health             健康检查 + 预算状态
  WS   /ws/analyze              建立分析会话,双向消息流

保护:
  - 按 IP 每日限流(RateLimiter)
  - 服务器日预算熔断(CostTracker)
  - CORS 只允许指定前端域名
"""
from __future__ import annotations

import asyncio
import logging
import os
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

# ---------- 先加载 .env,再导入依赖它的模块 ----------
PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(PROJECT_ROOT / ".env", override=False)

from src.agent import Agent, AgentEvent  # noqa: E402
from src.cost_tracker import CostTracker  # noqa: E402
from src.rate_limiter import RateLimiter  # noqa: E402
from src.tron_client import TronClient  # noqa: E402

logger = logging.getLogger("scamhunter")
logging.basicConfig(level=logging.INFO, format="[%(asctime)s] %(levelname)s %(name)s: %(message)s")

# ---------- 配置 ----------
FRONTEND_ORIGINS = [
    o.strip()
    for o in os.environ.get(
        "FRONTEND_ORIGINS",
        "https://scamhunter.gwcapital.xyz,https://scamhunter.gwcapital.cc,https://gwcapital-scamhunter.pages.dev,http://localhost:8000,http://localhost:8080,http://localhost:8765,http://127.0.0.1:8000,http://127.0.0.1:8080,http://127.0.0.1:8765",
    ).split(",")
    if o.strip()
]

DAILY_BUDGET_USD = float(os.environ.get("DAILY_BUDGET_USD", "5.0"))
DAILY_LIMIT_PER_IP = int(os.environ.get("DAILY_LIMIT_PER_IP", "3"))
PHASE_DECISION_TIMEOUT_S = int(os.environ.get("PHASE_DECISION_TIMEOUT_S", "900"))  # 15 分钟

# ---------- 应用 ----------
app = FastAPI(title="GWCAPITAL ScamHunter API", version="0.4.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=FRONTEND_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

cost_tracker = CostTracker(daily_budget_usd=DAILY_BUDGET_USD)
rate_limiter = RateLimiter(daily_limit_per_ip=DAILY_LIMIT_PER_IP)


# ---------- HTTP 路由 ----------

@app.get("/")
async def root() -> dict:
    return {
        "service": "GWCAPITAL · TRON 链诈骗分析器",
        "version": "0.4.0",
        "frontend": "https://scamhunter.gwcapital.xyz",
    }


@app.get("/api/health")
async def health() -> dict:
    return {
        "ok": True,
        "service": "gwcapital-scamhunter",
        "budget": cost_tracker.stats(),
        "rate_limit_per_ip": DAILY_LIMIT_PER_IP,
    }


@app.get("/healthz")
async def healthz() -> dict:
    """Fly 存活探测。外部数据源异常不应误杀正常 Web 进程。"""
    return {"status": "ok", "service": "gwcapital-scamhunter"}


def _client_ip_from_request(request: Request) -> str:
    """从 Fly / Cloudflare 的转发头提取真实 IP,降级到连接 IP。"""
    for h in ("fly-client-ip", "cf-connecting-ip", "x-forwarded-for"):
        v = request.headers.get(h)
        if v:
            return v.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


@app.get("/api/quota")
async def quota_for_ip(request: Request) -> dict:
    """前端直接调,自动从请求头提取 IP,不用传参。"""
    ip = _client_ip_from_request(request)
    return {
        "ip": ip,
        "used_today": DAILY_LIMIT_PER_IP - rate_limiter.remaining(ip),
        "remaining_today": rate_limiter.remaining(ip),
        "daily_limit": DAILY_LIMIT_PER_IP,
        "blocked": rate_limiter.is_blocked(ip),
        "server_budget_ok": cost_tracker.has_budget(),
        "server_budget_remaining_usd": round(cost_tracker.remaining_usd(), 2),
    }


# ---------- WebSocket ----------

def _client_ip(websocket: WebSocket) -> str:
    # Fly.io / Cloudflare 转发头优先
    for h in ("fly-client-ip", "cf-connecting-ip", "x-forwarded-for"):
        v = websocket.headers.get(h)
        if v:
            return v.split(",")[0].strip()
    return websocket.client.host if websocket.client else "unknown"


@app.websocket("/ws/analyze")
async def ws_analyze(websocket: WebSocket) -> None:
    # CORSMiddleware 不覆盖 WebSocket，必须单独校验 Origin，防止第三方网页
    # 借访客 IP 消耗本站 DeepSeek 预算与免费次数。
    origin = (websocket.headers.get("origin") or "").rstrip("/")
    if origin not in FRONTEND_ORIGINS:
        logger.warning("WS rejected origin=%s", origin or "missing")
        await websocket.close(code=1008)
        return

    ip = _client_ip(websocket)

    # 熔断 1:服务器日预算
    if not cost_tracker.has_budget():
        await websocket.accept()
        await websocket.send_json({
            "type": "error",
            "data": {"message": "服务器今日 API 预算已用完,请明天再来。如急需请在 GitHub 自部署。"},
        })
        await websocket.close(code=1008)
        return

    # 熔断 2:按 IP 限流
    allowed, used, limit = rate_limiter.try_consume(ip)
    if not allowed:
        await websocket.accept()
        if rate_limiter.is_blocked(ip):
            msg = "你的 IP 已被封禁"
        else:
            msg = f"今日免费额度已用完(每 IP 每日 {limit} 次,你已用 {used})。明日 00:00 重置。"
        await websocket.send_json({"type": "error", "data": {"message": msg}})
        await websocket.close(code=1008)
        return

    await websocket.accept()
    logger.info(f"WS accepted ip={ip} used={used}/{limit}")

    try:
        # 首条消息必须是 start
        first = await asyncio.wait_for(websocket.receive_json(), timeout=30)
        if first.get("action") != "start":
            await websocket.send_json({"type": "error", "data": {"message": "首条消息必须 action=start"}})
            await websocket.close(code=1003)
            return

        address = (first.get("address") or "").strip()
        user_context = (first.get("user_context") or "").strip()[:2000]
        if not address or not address.startswith("T") or len(address) != 34:
            await websocket.send_json({"type": "error", "data": {"message": "地址格式不正确"}})
            await websocket.close(code=1003)
            return

        # 共享 WS 发送器
        async def _ws_send(payload: dict) -> None:
            try:
                await websocket.send_json(payload)
            except Exception:
                pass

        def schedule_send(payload: dict) -> None:
            asyncio.create_task(_ws_send(payload))

        # 会话级 token / 成本累积(用于前端顶栏实时显示)
        from src.cost_tracker import (
            DEEPSEEK_INPUT_USD_PER_MTOKEN as IN_RATE,
            DEEPSEEK_OUTPUT_USD_PER_MTOKEN as OUT_RATE,
        )
        session_usage = {"prompt_tokens": 0, "completion_tokens": 0, "cost_usd": 0.0}

        def on_usage(p: int, c: int) -> None:
            cost_tracker.record_usage(p, c)
            session_usage["prompt_tokens"] += p
            session_usage["completion_tokens"] += c
            session_usage["cost_usd"] = round(
                (session_usage["prompt_tokens"] / 1_000_000) * IN_RATE
                + (session_usage["completion_tokens"] / 1_000_000) * OUT_RATE,
                4,
            )
            schedule_send({"type": "usage_update", "data": dict(session_usage)})

        agent = Agent(address, user_context=user_context, on_usage=on_usage)

        # 工具调用后需要刷新右栏 Mermaid / 左栏地址列表
        GRAPH_TOUCHING_TOOLS = {
            "analyze_address",
            "get_address_transactions",
            "check_approvals",
            "mark_branch_complete",
            "record_finding",
        }

        def emit(event: AgentEvent) -> None:
            schedule_send({"type": event.type, "data": event.data})
            if event.type == "tool_result":
                name = event.data.get("name", "")
                if name in GRAPH_TOUCHING_TOOLS:
                    schedule_send({
                        "type": "graph_snapshot",
                        "data": agent.graph.snapshot(),
                    })

        await websocket.send_json({"type": "session_start", "data": {
            "address": address,
            "remaining_today": rate_limiter.remaining(ip),
        }})

        async with TronClient() as client:
            while True:
                # 跑到下一个 pause 或 end
                ev = await agent.run_until_pause_or_end(client, on_event=emit)

                # 推当前 graph 快照
                await websocket.send_json({
                    "type": "graph_snapshot",
                    "data": agent.graph.snapshot(),
                })

                # 预算耗尽?终止
                if not cost_tracker.has_budget():
                    await websocket.send_json({
                        "type": "error",
                        "data": {"message": "本次分析过程中服务器预算耗尽,会话终止"},
                    })
                    break

                if ev.type == "phase_summary":
                    # 等用户决策
                    try:
                        decision = await asyncio.wait_for(
                            websocket.receive_json(), timeout=PHASE_DECISION_TIMEOUT_S
                        )
                    except asyncio.TimeoutError:
                        await websocket.send_json({
                            "type": "error",
                            "data": {"message": f"{PHASE_DECISION_TIMEOUT_S // 60} 分钟无响应,会话自动关闭"},
                        })
                        break

                    action = decision.get("action")
                    if action != "decision":
                        await websocket.send_json({"type": "error", "data": {"message": "期望 action=decision"}})
                        break
                    choice = decision.get("choice")
                    note = (decision.get("note") or "").strip()[:500]

                    if choice == "continue":
                        agent.resume_continue(note)
                        continue
                    if choice == "finish":
                        agent.resume_finish()
                        continue
                    if choice == "quit":
                        await websocket.send_json({"type": "session_end", "data": {"reason": "user_quit"}})
                        break
                    await websocket.send_json({"type": "error", "data": {"message": f"无效 choice: {choice}"}})
                    break
                else:
                    # final_report / done / error
                    await websocket.send_json({"type": "session_end", "data": {"reason": ev.type, "data": ev.data}})
                    break

    except WebSocketDisconnect:
        logger.info(f"WS disconnected ip={ip}")
    except asyncio.TimeoutError:
        logger.info(f"WS timeout ip={ip}")
    except Exception as e:
        logger.exception(f"WS error ip={ip}: {e}")
        try:
            await websocket.send_json({"type": "error", "data": {"message": f"Agent error: {e}"}})
        except Exception:
            pass
    finally:
        try:
            await websocket.close()
        except Exception:
            pass


# ---------- 本地开发入口 ----------
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("src.server:app", host="0.0.0.0", port=8000, reload=True)
