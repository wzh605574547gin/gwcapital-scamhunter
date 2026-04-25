#!/bin/bash
# GWCAPITAL · TRON ScamHunter 双击启动器
# 把这个文件双击运行即可打开应用。首次启动会自动装依赖。
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
  osascript -e 'display alert "GWCAPITAL · SCAMHUNTER" message "未找到可用的 Python。\n\n请先安装 Python 3.11 或 3.12，然后再次双击运行。" as critical' || true
  exit 1
fi

UV_BIN="$(command -v uv || true)"
if [ -z "$UV_BIN" ]; then
  osascript -e "display alert \"GWCAPITAL · SCAMHUNTER\" message \"未找到 uv。\\n\\n请先在终端执行：\\n\\n$PYTHON_BIN -m pip install --user uv\" as critical" || true
  exit 1
fi

if [ ! -f "$PROJECT_ENV" ] && [ ! -f "$HOME_ENV" ]; then
  osascript -e "display alert \"GWCAPITAL · SCAMHUNTER\" message \"未找到 .env 配置文件。\\n\\n请先复制 .env.example 为 .env，并填入：\\n  - TRON_PRO_API_KEY\\n  - DEEPSEEK_API_KEY\\n\\n支持的配置位置：\\n  1. $PROJECT_ENV\\n  2. $HOME_ENV\" as critical" || true
  exit 1
fi

if [ ! -d ".venv" ]; then
  echo "[BOOT] 首次启动，正在安装依赖..."
  "$UV_BIN" sync --python "$PYTHON_BIN"
fi

echo "[BOOT] 正在启动 TRON ScamHunter..."
"$UV_BIN" run python -m src.main
