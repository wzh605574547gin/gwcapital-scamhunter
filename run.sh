#!/bin/bash
# 启动 TRON ScamHunter 桌面应用
set -e

DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$DIR"

PROJECT_ENV="$DIR/.env"
HOME_ENV="$HOME/.tron_scam_agent/.env"

find_python() {
  for candidate in python3.12 python3.11 python3; do
    if command -v "$candidate" >/dev/null 2>&1; then
      if "$candidate" -c 'import sys; raise SystemExit(0 if (3, 11) <= sys.version_info[:2] < (3, 13) else 1)' >/dev/null 2>&1; then
        echo "$candidate"
        return 0
      fi
    fi
  done
  return 1
}

PYTHON_BIN="$(find_python || true)"
if [ -z "$PYTHON_BIN" ]; then
  echo "未找到可用的 Python。请先安装 Python 3.11 或 3.12 后再运行。"
  echo "推荐：macOS 用户可从 python.org 安装，或执行 brew install python@3.12"
  exit 1
fi

UV_BIN="$(command -v uv || true)"
if [ -z "$UV_BIN" ]; then
  echo "未找到 uv。请先运行："
  echo "  $PYTHON_BIN -m pip install --user uv"
  exit 1
fi

if [ ! -f "$PROJECT_ENV" ] && [ ! -f "$HOME_ENV" ]; then
  echo "未找到 .env 配置文件。"
  echo "请先执行：cp .env.example .env"
  echo "然后填写以下两项："
  echo "  - TRON_PRO_API_KEY"
  echo "  - DEEPSEEK_API_KEY"
  echo ""
  echo "支持的配置位置："
  echo "  - $PROJECT_ENV"
  echo "  - $HOME_ENV"
  exit 1
fi

if [ ! -d ".venv" ]; then
  echo "首次启动，正在安装依赖..."
  "$UV_BIN" sync --python "$PYTHON_BIN"
fi

echo "正在启动 TRON ScamHunter..."
"$UV_BIN" run python -m src.main
