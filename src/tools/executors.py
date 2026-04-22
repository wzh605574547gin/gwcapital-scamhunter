"""工具执行器——把 LLM 的工具调用翻译成 TronClient 调用 + 更新 graph。

每个函数返回 JSON 可序列化 dict,外层把它塞进 tool message content。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from src.memory.graph import AddressGraph
from src.tron_client import TronClient, TronScanError


@dataclass
class ToolContext:
    client: TronClient
    graph: AddressGraph


# ---------- 单个工具实现 ----------

async def tool_analyze_address(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    address = args["address"]

    # 去重:如果已分析过,直接返回缓存 + 明显标记
    cached = ctx.graph.get_cached(address)
    if cached is not None:
        return {"skipped": "already_analyzed", "address": address, "cached": cached}

    try:
        info = await ctx.client.get_account_info(address)
        sec = await ctx.client.get_security_data(address)
    except TronScanError as e:
        return {"error": f"TronScan 错误: {e}", "address": address}

    ctx.graph.mark_analyzed(address, info, sec)
    return {"account_info": info, "security_data": sec}


async def tool_get_address_transactions(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    address = args["address"]
    transfer_type = args["transfer_type"]
    limit = min(int(args.get("limit", 20)), 50)

    try:
        if transfer_type == "TRX":
            txs = await ctx.client.get_transactions(address, limit=limit)
            for tx in txs:
                src, dst = tx.get("from"), tx.get("to")
                amt = tx.get("amount_trx", 0)
                if src and dst and amt:
                    ctx.graph.add_edge(src, dst, amt, "TRX", tx.get("hash", ""), tx.get("timestamp"))
        else:
            txs = await ctx.client.get_trc20_transfers(address, limit=limit)
            for tx in txs:
                src, dst = tx.get("from"), tx.get("to")
                amt = tx.get("amount", 0)
                sym = tx.get("token_symbol") or "TRC20"
                if src and dst:
                    ctx.graph.add_edge(src, dst, amt, sym, tx.get("hash", ""), tx.get("timestamp"))
    except TronScanError as e:
        return {"error": f"TronScan 错误: {e}", "address": address}

    # 告诉 LLM 哪些对手方还没分析过
    counter_parties = set()
    for tx in txs:
        for key in ("from", "to"):
            a = tx.get(key)
            if a and a != address:
                counter_parties.add(a)
    unanalyzed = [a for a in counter_parties if not ctx.graph.is_analyzed(a)]

    return {
        "count": len(txs),
        "transactions": txs,
        "unanalyzed_counter_parties": unanalyzed[:10],
    }


async def tool_analyze_token(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    contract = args["contract_address"]
    try:
        return await ctx.client.get_token_security(contract)
    except TronScanError as e:
        return {"error": f"TronScan 错误: {e}", "contract": contract}


async def tool_mark_branch_complete(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    ctx.graph.mark_branch_complete(args["address"], args["reason"], args["summary"])
    return {"ok": True, "marked": args["address"]}


async def tool_record_finding(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    ctx.graph.add_finding(
        severity=args["severity"],
        title=args["title"],
        description=args["description"],
        related_addresses=args.get("related_addresses"),
    )
    return {"ok": True, "findings_total": len(ctx.graph.findings)}


async def tool_request_user_decision(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    """特殊:不做实际处理,把参数传回外层循环由主控处理暂停。"""
    return {
        "__paused__": True,
        "current_verdict": args["current_verdict"],
        "confidence": args["confidence"],
        "summary_markdown": args["summary_markdown"],
        "suggested_next_steps": args.get("suggested_next_steps", []),
    }


# ---------- 分发器 ----------

DISPATCH = {
    "analyze_address": tool_analyze_address,
    "get_address_transactions": tool_get_address_transactions,
    "analyze_token": tool_analyze_token,
    "mark_branch_complete": tool_mark_branch_complete,
    "record_finding": tool_record_finding,
    "request_user_decision": tool_request_user_decision,
}


async def execute(ctx: ToolContext, name: str, args: dict[str, Any]) -> dict[str, Any]:
    fn = DISPATCH.get(name)
    if fn is None:
        return {"error": f"未知工具: {name}"}
    return await fn(ctx, args)
