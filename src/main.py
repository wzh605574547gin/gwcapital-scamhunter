"""PyWebView 主入口 — 打开 macOS 原生窗口,内部渲染 frontend/index.html。"""
from __future__ import annotations

from pathlib import Path

import webview
from dotenv import load_dotenv

from src.api import API

PROJECT_ROOT = Path(__file__).resolve().parent.parent
FRONTEND_INDEX = PROJECT_ROOT / "frontend" / "index.html"
ENV_FILE = PROJECT_ROOT / ".env"


def main() -> None:
    # 启动时加载 .env,让 Agent 在后台线程里能读到 API Keys
    if ENV_FILE.exists():
        load_dotenv(ENV_FILE)

    if not FRONTEND_INDEX.exists():
        raise FileNotFoundError(f"找不到前端入口:{FRONTEND_INDEX}")

    api = API()
    window = webview.create_window(
        title="TRON ScamHunter",
        url=str(FRONTEND_INDEX),
        js_api=api,
        width=1400,
        height=900,
        min_size=(1200, 800),
        background_color="#0f172a",
    )
    api.window = window  # 反向引用,后续 agent 推事件用
    webview.start(debug=True)  # debug=True 开启 DevTools,方便联调


if __name__ == "__main__":
    main()
