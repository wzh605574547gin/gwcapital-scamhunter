"""OpenAI 兼容格式的工具定义——DeepSeek、Qwen、Kimi 等都吃这套 schema。

每个工具对应 executors.py 里的一个 async 函数。
"""
from __future__ import annotations

TOOL_DEFINITIONS: list[dict] = [
    {
        "type": "function",
        "function": {
            "name": "analyze_address",
            "description": (
                "综合查询一个 TRON 地址的基础信息和风控标签。"
                "一次调用拿到:余额、交易总数、创建时间、是否合约、多签结构、"
                "以及是否在黑名单/诈骗交易记录等风险标签。"
                "同一地址在本次会话中只会真正查一次,重复调用会返回缓存。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "address": {"type": "string", "description": "TRON 地址,T 开头 34 位"}
                },
                "required": ["address"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_address_transactions",
            "description": (
                "查询一个地址的转账记录,按时间倒序。"
                "transfer_type=TRC20 查 USDT 等代币转账,=TRX 查原生 TRX 转账。"
                "每笔返回:对手方、金额、时间、交易哈希。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "address": {"type": "string", "description": "目标地址"},
                    "transfer_type": {
                        "type": "string",
                        "enum": ["TRX", "TRC20"],
                        "description": "TRX=原生转账,TRC20=代币转账(推荐,USDT 走这里)",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "返回条数,默认 20,最大 50",
                        "default": 20,
                    },
                },
                "required": ["address", "transfer_type"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "analyze_token",
            "description": (
                "查询一个 TRC20 代币合约的安全等级与标签。"
                "返回:level(0-4)、vip 认证、各类 tag(red/grey/blue/public)、发行地址。"
                "用于判断地址持有的代币是否为诈骗币。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "contract_address": {
                        "type": "string",
                        "description": "代币合约地址,T 开头",
                    }
                },
                "required": ["contract_address"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "mark_branch_complete",
            "description": (
                "标记某一条追溯分支已查清,不再深入。"
                "适用于:资金流向了交易所/已知服务商、分支占比过小、证据已充分、深度到限。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "address": {"type": "string", "description": "本分支终点地址"},
                    "reason": {
                        "type": "string",
                        "enum": [
                            "reached_exchange",
                            "small_share",
                            "enough_evidence",
                            "max_depth",
                            "other",
                        ],
                    },
                    "summary": {"type": "string", "description": "为什么在这里停止,一句话说明"},
                },
                "required": ["address", "reason", "summary"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "record_finding",
            "description": (
                "记录一条关键发现,会进入最终报告的证据清单。"
                "发现可疑转账、命中风险标签、与已知诈骗地址关联等都应调用。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "severity": {
                        "type": "string",
                        "enum": ["info", "warning", "critical"],
                    },
                    "title": {"type": "string", "description": "一句话概括(≤30 字)"},
                    "description": {"type": "string", "description": "详细说明"},
                    "related_addresses": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "涉及的地址列表",
                    },
                },
                "required": ["severity", "title", "description"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "request_user_decision",
            "description": (
                "【特殊工具】触发阶段性暂停。当完成一个分析阶段时调用,"
                "系统会把你提供的结论展示给用户,让用户决定继续深挖还是结束报告。"
                "调用此工具后你本轮就结束,不要再调其他工具。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "current_verdict": {
                        "type": "string",
                        "enum": ["safe", "suspicious", "high_risk", "confirmed_scam"],
                    },
                    "confidence": {
                        "type": "string",
                        "enum": ["low", "medium", "high"],
                    },
                    "summary_markdown": {
                        "type": "string",
                        "description": "阶段性结论,严格按 system prompt 里的格式",
                    },
                    "suggested_next_steps": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "如果继续深挖,你会先做什么",
                    },
                },
                "required": ["current_verdict", "confidence", "summary_markdown"],
            },
        },
    },
]
