"""PyWebView 主入口 — 打开 macOS 原生窗口,内部渲染 frontend/index.html。"""
from __future__ import annotations

import os
from pathlib import Path

import webview
from dotenv import load_dotenv

from src.api import API

PROJECT_ROOT = Path(__file__).resolve().parent.parent
FRONTEND_INDEX = PROJECT_ROOT / "frontend" / "index.html"
ENV_CANDIDATES = [
    PROJECT_ROOT / ".env",
    Path.home() / ".tron_scam_agent" / ".env",
]
REQUIRED_ENV_VARS = ("TRON_PRO_API_KEY", "DEEPSEEK_API_KEY")


def _load_env() -> None:
    for env_file in ENV_CANDIDATES:
        if env_file.exists():
            load_dotenv(env_file)
            return

    env_paths = "\n".join(f"  - {path}" for path in ENV_CANDIDATES)
    raise RuntimeError(
        "未找到配置文件 .env。\n\n"
        "请先复制 .env.example 并填入 API Key，支持以下任一位置：\n"
        f"{env_paths}"
    )


def _validate_required_env() -> None:
    missing = [name for name in REQUIRED_ENV_VARS if not os.environ.get(name, "").strip()]
    if not missing:
        return

    missing_text = "\n".join(f"  - {name}" for name in missing)
    raise RuntimeError(
        "配置文件已加载，但以下必填项为空：\n"
        f"{missing_text}\n\n"
        "请编辑 .env 后重新启动。"
    )


def main() -> None:
    _load_env()
    _validate_required_env()

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
