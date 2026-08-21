"""TronScan REST API 封装。

对外暴露 6 个异步方法,每个返回精简过的 dict,只保留 Agent 决策需要的字段。
请求带 TRON-PRO-API-KEY,429 会指数退避重试。
"""
from __future__ import annotations

import os
from typing import Any

import httpx
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

BASE_URL = "https://apilist.tronscanapi.com"
DEFAULT_TIMEOUT = 20.0


class TronScanError(Exception):
    """TronScan API 返回非预期内容。"""


class TronScanRateLimited(Exception):
    """HTTP 429,被限流,交给 tenacity 重试。"""


def _api_key() -> str:
    key = os.environ.get("TRON_PRO_API_KEY", "").strip()
    if not key:
        raise TronScanError("TRON_PRO_API_KEY 未设置,请在 .env 中填入")
    return key


def _as_int(v: Any) -> int:
    """TronScan 返回的数值字段经常是 str,统一转 int。None/空串按 0 处理。"""
    if v is None or v == "":
        return 0
    try:
        return int(v)
    except (TypeError, ValueError):
        try:
            return int(float(v))
        except (TypeError, ValueError):
            return 0


def _as_float(v: Any) -> float:
    """同 _as_int 但转 float,用于 USD 价值、代币余额等。"""
    if v is None or v == "":
        return 0.0
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


class TronClient:
    """TronScan 异步客户端。

    用法:
        async with TronClient() as client:
            info = await client.get_account_info("TXxxx")
    """

    def __init__(self, api_key: str | None = None, timeout: float = DEFAULT_TIMEOUT):
        self._api_key = api_key or _api_key()
        self._client = httpx.AsyncClient(
            base_url=BASE_URL,
            headers={"TRON-PRO-API-KEY": self._api_key},
            timeout=timeout,
        )

    async def __aenter__(self) -> "TronClient":
        return self

    async def __aexit__(self, *_: Any) -> None:
        await self._client.aclose()

    async def close(self) -> None:
        await self._client.aclose()

    @retry(
        retry=retry_if_exception_type(TronScanRateLimited),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        reraise=True,
    )
    async def _get(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        resp = await self._client.get(path, params=params or {})
        if resp.status_code == 429:
            raise TronScanRateLimited(f"429 rate limited on {path}")
        if resp.status_code == 401:
            raise TronScanError("401 未授权:TRON_PRO_API_KEY 可能无效")
        if resp.status_code >= 400:
            raise TronScanError(f"HTTP {resp.status_code} on {path}: {resp.text[:200]}")
        try:
            return resp.json()
        except Exception as e:
            raise TronScanError(f"JSON 解析失败: {e}") from e

    # ---------- 6 个对外端点 ----------

    async def get_account_info(self, address: str) -> dict[str, Any]:
        """账户基础信息。提取:余额、最后活跃时间、交易总数、标签、权限结构。"""
        raw = await self._get("/api/accountv2", {"address": address})
        return {
            "address": raw.get("address"),
            "balance_trx": raw.get("balance", 0) / 1_000_000,
            "latest_operation_time": raw.get("latest_operation_time"),
            "date_created": raw.get("date_created"),
            "total_transaction_count": raw.get("totalTransactionCount"),
            "address_tag": raw.get("addressTag"),
            "public_tag": raw.get("publicTag"),
            "is_contract": bool(raw.get("accountType") == 1),
            "owner_permission": raw.get("ownerPermission"),
            "active_permissions": raw.get("activePermissions"),
        }

    async def get_security_data(self, address: str) -> dict[str, Any]:
        """风控标签——核心数据源。"""
        raw = await self._get("/api/security/account/data", {"address": address})
        return {
            "address": address,
            "send_ad_by_memo": raw.get("send_ad_by_memo", False),
            "has_fraud_transaction": raw.get("has_fraud_transaction", False),
            "fraud_token_creator": raw.get("fraud_token_creator", False),
            "is_black_list": raw.get("is_black_list", False),
            "is_receive_black_fund": raw.get("is_receive_black_fund", False),
            "raw_flags": raw,
        }

    async def get_transactions(self, address: str, limit: int = 20) -> list[dict[str, Any]]:
        """TRX 交易历史(最近 N 笔)。"""
        raw = await self._get(
            "/api/transaction",
            {"address": address, "limit": limit, "sort": "-timestamp"},
        )
        items = raw.get("data", []) or []
        return [
            {
                "hash": tx.get("hash"),
                "timestamp": tx.get("timestamp"),
                "from": tx.get("ownerAddress"),
                "to": tx.get("toAddress"),
                "contract_type": tx.get("contractType"),
                "amount_trx": _as_int(tx.get("amount")) / 1_000_000,
                "confirmed": tx.get("confirmed", False),
            }
            for tx in items
        ]

    async def get_trc20_transfers(self, address: str, limit: int = 20) -> list[dict[str, Any]]:
        """TRC20 转账(USDT 等),按时间倒序。"""
        raw = await self._get(
            "/api/token_trc20/transfers",
            {"relatedAddress": address, "limit": limit, "start": 0},
        )
        items = raw.get("token_transfers", []) or []
        out = []
        for tx in items:
            decimals = _as_int(tx.get("tokenInfo", {}).get("tokenDecimal", 6))
            quant = _as_int(tx.get("quant"))
            out.append(
                {
                    "hash": tx.get("transaction_id"),
                    "timestamp": tx.get("block_ts"),
                    "from": tx.get("from_address"),
                    "to": tx.get("to_address"),
                    "token_symbol": tx.get("tokenInfo", {}).get("tokenAbbr"),
                    "token_contract": tx.get("contract_address"),
                    "amount": quant / (10**decimals) if decimals else quant,
                    "confirmed": tx.get("confirmed", True),
                }
            )
        return out

    async def get_token_security(self, contract_address: str) -> dict[str, Any]:
        """代币安全等级与标签。

        level: '0' 未知 / '1' 中性 / '2' OK / '3' 可疑 / '4' 不安全
        redTag 非空 = 标红警告(高风险),greyTag 非空 = 灰名单
        vip=True 表示官方认证的主流代币
        """
        raw = await self._get("/api/token_trc20", {"contract": contract_address})
        tokens = raw.get("trc20_tokens") or []
        if not tokens:
            return {
                "contract": contract_address,
                "found": False,
                "token_level": None,
                "tags": {},
                "is_vip": False,
                "issue_address": None,
                "symbol": None,
                "name": None,
            }
        t = tokens[0]
        return {
            "contract": contract_address,
            "found": True,
            "symbol": t.get("symbol"),
            "name": t.get("name"),
            "token_level": t.get("level"),
            "tags": {
                "public": t.get("publicTag") or "",
                "red": t.get("redTag") or "",
                "grey": t.get("greyTag") or "",
                "blue": t.get("blueTag") or "",
            },
            "is_vip": bool(t.get("vip", False)),
            "issue_address": t.get("issue_address"),
            "issue_time": t.get("issue_time"),
            "holders_count": t.get("holders_count"),
            "total_supply": t.get("total_supply_str") or t.get("total_supply"),
        }

    async def get_address_approvals(self, address: str, limit: int = 30) -> list[dict[str, Any]]:
        """查一个地址的 TRC20 授权(approve)列表。

        关键字段:
        - unlimited: True 表示无上限授权(诈骗识别红线)
        - from_address / to_address / contract_address: 授权三方关系
        - project: 已知 DApp 的话会有 id/name
        """
        raw = await self._get(
            "/api/account/approve/list",
            {"address": address, "limit": limit, "start": 0},
        )
        items = raw.get("data") or []
        out: list[dict[str, Any]] = []
        for a in items:
            token_info = a.get("tokenInfo") or {}
            project = a.get("project") or {}
            out.append(
                {
                    "from_address": a.get("from_address"),
                    "to_address": a.get("to_address"),
                    "token_contract": a.get("contract_address"),
                    "token_symbol": token_info.get("tokenAbbr") or token_info.get("tokenName"),
                    "amount_raw": a.get("amount"),
                    "unlimited": bool(a.get("unlimited", False)),
                    "project_id": project.get("id"),
                    "project_name": project.get("name"),
                    "operate_time": a.get("operate_time"),
                }
            )
        return out

    async def get_contract_info(self, address: str) -> dict[str, Any]:
        """合约元信息:是否已验证源码、是否代理合约、创建时间。"""
        raw = await self._get("/api/contract", {"contract": address})
        items = raw.get("data") or []
        if not items:
            return {"found": False}
        d = items[0]
        return {
            "found": True,
            "verify_status": d.get("verify_status"),  # 0/1/2/3 数值
            "is_proxy": bool(d.get("is_proxy")),
            "proxy_implementation": d.get("proxy_implementation"),
            "trx_count": _as_int(d.get("trxCount")),
            "date_created": d.get("date_created"),
            "balance_trx": _as_float(d.get("balance", 0)) / 1_000_000,
            "balance_usd": _as_float(d.get("balanceInUsd")),
        }

    async def get_account_tokens(self, address: str) -> list[dict[str, Any]]:
        """账户持有的代币列表,按 USD 价值降序。

        TronScan 这个端点会帮我们预先算好:
        - amount: 已按 decimals 还原的人类可读余额
        - amountInUsd: 对应美元总价
        """
        raw = await self._get("/api/account/tokens", {"address": address})
        items = raw.get("data") or []
        out: list[dict[str, Any]] = []
        for t in items:
            amount_usd = _as_float(t.get("amountInUsd"))
            out.append(
                {
                    "symbol": t.get("tokenAbbr") or t.get("tokenName"),
                    "name": t.get("tokenName"),
                    "contract": t.get("tokenId"),
                    "balance": _as_float(t.get("amount")),
                    "amount_usd": round(amount_usd, 2),
                    "price_usd": _as_float(t.get("tokenPriceInUsd")),
                    "token_type": t.get("tokenType"),
                    "level": t.get("tokenLevel"),
                    "is_vip": bool(t.get("vip", False)),
                }
            )
        out.sort(key=lambda x: x["amount_usd"], reverse=True)
        return out
