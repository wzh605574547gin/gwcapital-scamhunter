#!/bin/bash
# GWCAPITAL · TRON ScamHunter macOS .app 打包脚本
# 产物:dist/TRON ScamHunter.app — 可拖进 Applications
#
# 限制:
# - 未做代码签名,首次运行 macOS 可能报"来自未识别开发者",右键 → 打开即可
# - 仅打包核心运行时,.env 不会嵌入;应用会优先读取项目目录 .env,找不到时再读取 ~/.tron_scam_agent/.env

set -e
DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$DIR"

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
  echo "[BUILD] 未找到可用的 Python。请先安装 Python 3.11 或 3.12。"
  exit 1
fi

UV_BIN="$(command -v uv || true)"
if [ -z "$UV_BIN" ]; then
  echo "[BUILD] 未找到 uv。请先运行："
  echo "        $PYTHON_BIN -m pip install --user uv"
  exit 1
fi

echo "[BUILD] 安装 pyinstaller(若缺)"
"$UV_BIN" pip install pyinstaller --python "$PYTHON_BIN" >/dev/null

echo "[BUILD] 清理旧产物"
rm -rf build dist __pycache__

echo "[BUILD] 运行 pyinstaller"
"$UV_BIN" run pyinstaller \
  --windowed \
  --name "TRON ScamHunter" \
  --osx-bundle-identifier "com.gwcapital.scamhunter" \
  --add-data "frontend:frontend" \
  --add-data "src/prompts:src/prompts" \
  --hidden-import webview.platforms.cocoa \
  --hidden-import openai \
  --noconfirm \
  src/main.py

echo ""
echo "[OK] 打包完成 · dist/TRON ScamHunter.app"
echo ""
echo "提示:首次运行前，请准备好 .env。应用支持以下任一位置："
echo "      1. $DIR/.env"
echo "      2. $HOME/.tron_scam_agent/.env"
echo "      小白用户优先推荐直接双击 run.command 跑源码。"
