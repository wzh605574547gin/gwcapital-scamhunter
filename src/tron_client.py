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

    async def get_account_tokens(self, address: str) -> list[dict[str, Any]]:
        """账户持有的代币列表。"""
        raw = await self._get("/api/account/tokens", {"address": address})
        items = raw.get("data", []) or []
        return [
            {
                "token_symbol": t.get("tokenAbbr") or t.get("tokenName"),
                "token_contract": t.get("tokenId"),
                "balance": t.get("balance"),
                "token_type": t.get("tokenType"),
            }
            for t in items
        ]
