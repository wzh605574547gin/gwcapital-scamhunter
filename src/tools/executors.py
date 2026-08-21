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

USDT_CONTRACT = "TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t"


def _compute_flows(address: str, transfers: list[dict[str, Any]]) -> dict[str, Any]:
    """聚合转账列表,按代币 symbol 统计进/出金额。"""
    from collections import defaultdict

    inflow: dict[str, float] = defaultdict(float)
    outflow: dict[str, float] = defaultdict(float)
    in_count: dict[str, int] = defaultdict(int)
    out_count: dict[str, int] = defaultdict(int)
    for tx in transfers:
        sym = tx.get("token_symbol") or "?"
        amt = float(tx.get("amount") or 0)
        if tx.get("to") == address:
            inflow[sym] += amt
            in_count[sym] += 1
        elif tx.get("from") == address:
            outflow[sym] += amt
            out_count[sym] += 1
    tokens_seen = set(inflow) | set(outflow)
    return {
        "window": f"最近 {len(transfers)} 笔 TRC20",
        "by_token": [
            {
                "symbol": sym,
                "inflow": round(inflow[sym], 2),
                "outflow": round(outflow[sym], 2),
                "net": round(inflow[sym] - outflow[sym], 2),
                "in_count": in_count[sym],
                "out_count": out_count[sym],
            }
            for sym in sorted(tokens_seen, key=lambda s: -(inflow[s] + outflow[s]))
        ],
    }


async def tool_analyze_address(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    address = args["address"]

    # 去重:如果已分析过,直接返回缓存 + 明显标记
    cached = ctx.graph.get_cached(address)
    if cached is not None:
        return {"skipped": "already_analyzed", "address": address, "cached": cached}

    try:
        info = await ctx.client.get_account_info(address)
        sec = await ctx.client.get_security_data(address)
        tokens = await ctx.client.get_account_tokens(address)
        # 拉最近 50 笔 TRC20 算流向(样本足够给 LLM 判断资金模式)
        recent_transfers = await ctx.client.get_trc20_transfers(address, limit=50)
    except TronScanError as e:
        return {"error": f"TronScan 错误: {e}", "address": address}

    # 压缩持仓:top 5 by USD 价值,强制保留 USDT(就算金额少)
    tokens_held = [t for t in tokens if t.get("balance", 0) > 0]
    top_tokens = tokens_held[:5]
    if not any(t["contract"] == USDT_CONTRACT for t in top_tokens):
        usdt = next((t for t in tokens_held if t["contract"] == USDT_CONTRACT), None)
        if usdt:
            top_tokens.append(usdt)

    holdings = {
        "top_tokens": [
            {
                "symbol": t["symbol"],
                "balance": round(t["balance"], 4),
                "usd_value": t["amount_usd"],
                "is_vip": t["is_vip"],
                "level": t["level"],
            }
            for t in top_tokens
        ],
        "total_tokens_held": len(tokens_held),
        "total_usd_value": round(sum(t["amount_usd"] for t in tokens_held), 2),
    }

    # 流向聚合(用刚拉的 50 笔算进/出金额,给 LLM 一个资金模式视角)
    flows = _compute_flows(address, recent_transfers)

    # 把聚合后的边也塞进 graph(方便 Mermaid 渲染)
    for tx in recent_transfers:
        src, dst = tx.get("from"), tx.get("to")
        if src and dst:
            ctx.graph.add_edge(
                src, dst,
                float(tx.get("amount") or 0),
                tx.get("token_symbol") or "TRC20",
                tx.get("hash", ""),
                tx.get("timestamp"),
            )

    result: dict[str, Any] = {
        "account_info": info,
        "security_data": sec,
        "holdings": holdings,
        "flows_recent": flows,
    }

    # 合约额外信息
    if info.get("is_contract"):
        try:
            result["contract_details"] = await ctx.client.get_contract_info(address)
        except TronScanError:
            pass

    ctx.graph.mark_analyzed(address, info, sec)
    return result


async def tool_check_approvals(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    """查一个地址的 TRC20 授权记录。"""
    address = args["address"]
    try:
        approvals = await ctx.client.get_address_approvals(address, limit=30)
    except TronScanError as e:
        return {"error": f"TronScan 错误: {e}", "address": address}

    # 高风险条件:unlimited=True 且没有已知 DApp 标识
    high_risk = [
        a for a in approvals
        if a.get("unlimited") and not a.get("project_name")
    ]
    return {
        "address": address,
        "approvals_total": len(approvals),
        "high_risk_count": len(high_risk),
        "high_risk_approvals": high_risk[:10],
        "all_approvals": approvals[:15],
    }


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
    "check_approvals": tool_check_approvals,
    "mark_branch_complete": tool_mark_branch_complete,
    "record_finding": tool_record_finding,
    "request_user_decision": tool_request_user_decision,
}


async def execute(ctx: ToolContext, name: str, args: dict[str, Any]) -> dict[str, Any]:
    fn = DISPATCH.get(name)
    if fn is None:
        return {"error": f"未知工具: {name}"}
    return await fn(ctx, args)
