#!/bin/bash
# GWCAPITAL · TRON ScamHunter macOS .app 打包脚本
# 产物:dist/TRON ScamHunter.app — 可拖进 Applications
#
# 限制:
# - 未做代码签名,首次运行 macOS 可能报"来自未识别开发者",右键 → 打开即可
# - 仅打包核心运行时,.env 不会嵌入;首次启动会读取 ~/.tron_scam_agent/.env(若不存在则报错)

set -e
DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$DIR"

UV_BIN="$HOME/Library/Python/3.12/bin/uv"
[ ! -x "$UV_BIN" ] && UV_BIN="$(command -v uv)"

echo "[BUILD] 安装 pyinstaller(若缺)"
"$UV_BIN" pip install pyinstaller --python python3.12 >/dev/null

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
echo "提示:首次运行前,请把 .env 放到 ~/.tron_scam_agent/.env"
echo "     或双击 run.command 直接跑源码(更稳)"
