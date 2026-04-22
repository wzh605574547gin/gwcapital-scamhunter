"""本次任务的地址关系图与去重状态。

主要职责:
- 记录哪些地址已经深度分析过(调用过 analyze_address)
- 记录哪些地址只是被"发现"(作为对手方出现在转账里,未深入)
- 记录地址之间的转账边(用于生成 Mermaid 图)
- 记录分支完成状态和关键发现
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class AddressRecord:
    address: str
    account_info: dict[str, Any] | None = None
    security_data: dict[str, Any] | None = None
    is_analyzed: bool = False
    branch_complete: bool = False
    complete_reason: str | None = None
    complete_summary: str | None = None
    public_tag: str | None = None


@dataclass
class TransferEdge:
    src: str
    dst: str
    amount: float
    token: str  # "TRX" / "USDT" / 其他
    tx_hash: str
    timestamp: int | None = None


@dataclass
class Finding:
    severity: str  # "info" / "warning" / "critical"
    title: str
    description: str
    related_addresses: list[str] = field(default_factory=list)


class AddressGraph:
    """维护本次任务的地址关系图。"""

    def __init__(self, target_address: str):
        self.target = target_address
        self.addresses: dict[str, AddressRecord] = {}
        self.edges: list[TransferEdge] = []
        self.findings: list[Finding] = []
        self._mark_discovered(target_address)

    # ---------- 地址发现与分析 ----------

    def _mark_discovered(self, address: str) -> AddressRecord:
        """首次提到一个地址——还没深入分析。"""
        if address not in self.addresses:
            self.addresses[address] = AddressRecord(address=address)
        return self.addresses[address]

    def is_analyzed(self, address: str) -> bool:
        rec = self.addresses.get(address)
        return bool(rec and rec.is_analyzed)

    def mark_analyzed(
        self,
        address: str,
        account_info: dict[str, Any],
        security_data: dict[str, Any],
    ) -> None:
        rec = self._mark_discovered(address)
        rec.account_info = account_info
        rec.security_data = security_data
        rec.is_analyzed = True
        rec.public_tag = account_info.get("public_tag") or account_info.get("address_tag")

    def get_cached(self, address: str) -> dict[str, Any] | None:
        rec = self.addresses.get(address)
        if not rec or not rec.is_analyzed:
            return None
        return {
            "account_info": rec.account_info,
            "security_data": rec.security_data,
        }

    def mark_branch_complete(self, address: str, reason: str, summary: str) -> None:
        rec = self._mark_discovered(address)
        rec.branch_complete = True
        rec.complete_reason = reason
        rec.complete_summary = summary

    # ---------- 转账边 ----------

    def add_edge(
        self,
        src: str,
        dst: str,
        amount: float,
        token: str,
        tx_hash: str,
        timestamp: int | None = None,
    ) -> None:
        self._mark_discovered(src)
        self._mark_discovered(dst)
        self.edges.append(
            TransferEdge(src=src, dst=dst, amount=amount, token=token, tx_hash=tx_hash, timestamp=timestamp)
        )

    # ---------- 发现 ----------

    def add_finding(
        self,
        severity: str,
        title: str,
        description: str,
        related_addresses: list[str] | None = None,
    ) -> None:
        self.findings.append(
            Finding(
                severity=severity,
                title=title,
                description=description,
                related_addresses=related_addresses or [],
            )
        )

    # ---------- 状态查询 ----------

    def stats(self) -> dict[str, int]:
        return {
            "addresses_discovered": len(self.addresses),
            "addresses_analyzed": sum(1 for r in self.addresses.values() if r.is_analyzed),
            "edges": len(self.edges),
            "findings": len(self.findings),
            "branches_complete": sum(1 for r in self.addresses.values() if r.branch_complete),
        }

    def analyzed_list(self) -> list[str]:
        return [a for a, r in self.addresses.items() if r.is_analyzed]

    # ---------- 前端快照与 mermaid 渲染 ----------

    def snapshot(self) -> dict[str, Any]:
        """给前端用的紧凑快照——不含原始交易数据,只够渲染左栏和右栏。"""
        return {
            "target": self.target,
            "stats": self.stats(),
            "analyzed": [
                {
                    "address": a,
                    "public_tag": r.public_tag,
                    "is_contract": bool(r.account_info and r.account_info.get("is_contract")),
                    "branch_complete": r.branch_complete,
                    "risk_flags": _risk_flags(r),
                }
                for a, r in self.addresses.items() if r.is_analyzed
            ],
            "findings": [
                {
                    "severity": f.severity,
                    "title": f.title,
                    "description": f.description,
                    "related_addresses": f.related_addresses,
                }
                for f in self.findings
            ],
            "mermaid": self.to_mermaid(),
        }

    def to_mermaid(self, max_edges: int = 40) -> str:
        """生成 mermaid graph LR 语法。同 (src, dst, token) 的边会聚合。"""
        from collections import defaultdict

        if not self.addresses:
            return "graph LR\n    empty[暂无数据]"

        # 聚合边
        agg: dict[tuple[str, str, str], dict[str, Any]] = defaultdict(
            lambda: {"total": 0.0, "count": 0}
        )
        for e in self.edges:
            key = (e.src, e.dst, e.token)
            agg[key]["total"] += e.amount
            agg[key]["count"] += 1

        # 只保留金额最大的 N 条边,避免图太乱
        sorted_edges = sorted(agg.items(), key=lambda kv: -kv[1]["total"])[:max_edges]

        # 参与边的节点优先显示,剩下的按已分析的展示
        nodes_in_edges: set[str] = set()
        for (s, d, _), _rec in sorted_edges:
            nodes_in_edges.add(s)
            nodes_in_edges.add(d)
        nodes_to_draw = nodes_in_edges | set(self.analyzed_list()) | {self.target}

        lines = ["graph LR"]
        for addr in nodes_to_draw:
            rec = self.addresses.get(addr)
            label = _label(addr, rec)
            node_id = _node_id(addr)
            cls = _node_class(addr, rec, self.target)
            lines.append(f"    {node_id}[\"{label}\"]:::{cls}")

        for (src, dst, token), rec in sorted_edges:
            total = rec["total"]
            count = rec["count"]
            edge_label = _edge_label(total, token, count)
            lines.append(f"    {_node_id(src)} -->|\"{edge_label}\"| {_node_id(dst)}")

        # 样式定义——深色主题
        lines.append("    classDef target fill:#ef4444,stroke:#fca5a5,color:#fff,stroke-width:2px")
        lines.append("    classDef analyzed fill:#1e40af,stroke:#60a5fa,color:#fff")
        lines.append("    classDef discovered fill:#334155,stroke:#64748b,color:#cbd5e1")
        lines.append("    classDef done fill:#064e3b,stroke:#34d399,color:#a7f3d0")
        lines.append("    classDef risk fill:#7f1d1d,stroke:#fca5a5,color:#fee2e2,stroke-width:2px")
        return "\n".join(lines)


# ---------- 内部工具 ----------

def _risk_flags(rec: AddressRecord) -> list[str]:
    flags: list[str] = []
    sec = rec.security_data or {}
    for k in ("has_fraud_transaction", "is_black_list", "fraud_token_creator", "is_receive_black_fund", "send_ad_by_memo"):
        if sec.get(k):
            flags.append(k)
    return flags


def _label(addr: str, rec: AddressRecord | None) -> str:
    """节点显示名——优先用 public_tag,否则用缩略地址。"""
    tag = rec.public_tag if rec else None
    if tag:
        return tag[:18]
    return f"{addr[:6]}...{addr[-4:]}"


def _node_id(addr: str) -> str:
    """mermaid 节点 ID——用地址本身(base58 都是安全字符)。"""
    return addr


def _node_class(addr: str, rec: AddressRecord | None, target: str) -> str:
    if addr == target:
        return "target"
    if not rec:
        return "discovered"
    if _risk_flags(rec):
        return "risk"
    if rec.branch_complete:
        return "done"
    if rec.is_analyzed:
        return "analyzed"
    return "discovered"


def _edge_label(total: float, token: str, count: int) -> str:
    if total >= 1_000_000:
        amt = f"{total/1_000_000:.1f}M"
    elif total >= 1000:
        amt = f"{total/1000:.1f}K"
    else:
        amt = f"{total:.1f}"
    if count > 1:
        return f"{amt} {token} x{count}"
    return f"{amt} {token}"
