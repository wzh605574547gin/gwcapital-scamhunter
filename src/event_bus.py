"""事件总线——把后端事件序列化后推送到前端 (JS)。

用 window.evaluate_js 触发前端注册的 window.__onAgentEvent(ev) 回调。
双重 JSON 编码以保证任意字符串(含引号、反斜杠、中文、换行)都能安全注入。
"""
from __future__ import annotations

import json
from typing import Any


class EventBus:
    def __init__(self, window):
        self.window = window

    def emit(self, event_type: str, data: dict[str, Any] | None = None) -> None:
        if self.window is None:
            return
        payload = {"type": event_type, "data": data or {}}
        # 先把 payload 编码为 JSON 字符串,再把这个字符串再编码一次作为 JS 字面量
        # 这样前端 JSON.parse() 即可拿到原始对象
        event_json = json.dumps(payload, ensure_ascii=False, default=str)
        js_literal = json.dumps(event_json, ensure_ascii=False)
        js = f"window.__onAgentEvent && window.__onAgentEvent(JSON.parse({js_literal}))"
        try:
            self.window.evaluate_js(js)
        except Exception as e:
            # 不让前端事件失败影响 Agent 主循环
            print(f"[event_bus] evaluate_js 失败 (type={event_type}): {e}")
