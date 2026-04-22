#!/bin/bash
# GWCAPITAL · TRON ScamHunter 双击启动器
# 把这个文件双击运行即可打开应用。首次启动会自动装依赖。
set -e

DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$DIR"

if [ ! -f ".env" ]; then
  osascript -e 'display alert "GWCAPITAL · SCAMHUNTER" message "未找到 .env 文件。\n\n请复制 .env.example 为 .env,并填入:\n  - TRON_PRO_API_KEY\n  - DEEPSEEK_API_KEY\n\n然后再次运行。" as critical' || true
  exit 1
fi

UV_BIN="$HOME/Library/Python/3.12/bin/uv"
if [ ! -x "$UV_BIN" ]; then
  UV_BIN="$(command -v uv || true)"
fi
if [ -z "$UV_BIN" ]; then
  osascript -e 'display alert "GWCAPITAL · SCAMHUNTER" message "未找到 uv。\n请先运行:\n\npython3.12 -m pip install --user uv" as critical' || true
  exit 1
fi

if [ ! -d ".venv" ]; then
  echo "[BOOT] 首次启动,正在安装依赖…"
  "$UV_BIN" sync --python python3.12
fi

"$UV_BIN" run python -m src.main
