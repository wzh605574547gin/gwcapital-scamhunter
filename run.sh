#!/bin/bash
# 启动 TRON ScamHunter 桌面应用
set -e
cd "$(dirname "$0")"

UV_BIN="$HOME/Library/Python/3.12/bin/uv"
if [ ! -x "$UV_BIN" ]; then
  echo "未找到 uv,请先运行:python3.12 -m pip install --user uv"
  exit 1
fi

if [ ! -d ".venv" ]; then
  echo "首次启动,正在安装依赖…"
  "$UV_BIN" sync --python python3.12
fi

"$UV_BIN" run python -m src.main
