# GWCAPITAL · TRON ScamHunter

> **AI 驱动的 TRON 链上诈骗追溯工具** — 桌面原生 · 赛博朋克风 · DeepSeek 驱动

一个在 macOS 本地跑的 TRON 地址风险分析 Agent。你丢一个地址 + 简短背景信息进去,AI 会**自主调用 TronScan 链上 API** 追溯资金流向、识别风险标签、生成 Mermaid 关系图,每个分析阶段结束会暂停等你决定是否继续深挖,最后输出结构化报告。

---

## 特性

- 🔍 **多轮 Agent Loop** — AI 自主规划工具调用、递归追溯、阶段性汇报
- 🎯 **TronScan 深度集成** — 账户信息 / 风控标签 / TRC20 转账 / 代币安全等级 / 多签结构
- 🧠 **用户背景信息注入** — 自然语言描述会被 AI 与链上数据交叉验证
- 🎨 **赛博朋克终端风 UI** — 网格背景、霓虹描边、CRT 扫描线、Mermaid 实时绘图
- 🇨🇳 **原生中文推理** — 依托 DeepSeek V3,性价比约为 Claude 的 1/10
- 🔒 **纯本地运行** — 不上传任何数据,API Key 只存本机 `.env`

---

## 技术栈

| 层 | 选型 |
|---|---|
| 桌面框架 | PyWebView(原生 macOS 窗口,内嵌 WebKit) |
| 前端 | 纯 HTML/CSS/JS + Tailwind CDN + Mermaid + marked |
| 后端 | Python 3.12,asyncio,httpx,SQLAlchemy(预留) |
| AI 模型 | **DeepSeek V3**(OpenAI 兼容接口) |
| 链上数据 | **TronScan REST API** |

---

## 安装 & 运行

### 第一次跑

1. 装 Python 3.12(python.org 下载 pkg 或 `brew install python@3.12`)
2. 装 uv:
   ```bash
   python3.12 -m pip install --user uv
   ```
3. 克隆仓库:
   ```bash
   git clone <your-repo-url> ~/Projects/tron-scam-agent
   cd ~/Projects/tron-scam-agent
   ```
4. 准备 API Key:
   ```bash
   cp .env.example .env
   # 编辑 .env,填入 TRON_PRO_API_KEY 和 DEEPSEEK_API_KEY
   ```
5. 启动:
   ```bash
   ./run.sh          # 终端启动
   # 或者在 Finder 里双击 run.command
   ```

### 打包成 .app(可选)

```bash
./build_app.sh
# 产物: dist/TRON ScamHunter.app
```

> 首次双击打开会报"来自未识别的开发者"—— **右键 → 打开** 即可放行。

---

## API Key 申请

| Key | 申请地址 | 费用 |
|---|---|---|
| TronScan | https://tronscan.org/#/myaccount/apiKeys/ | 免费 |
| DeepSeek | https://platform.deepseek.com | 充 ¥10 够跑几百次分析 |

---

## 项目结构

```
tron-scam-agent/
├── run.sh / run.command    # 启动脚本 / 双击启动器
├── build_app.sh            # .app 打包脚本
├── pyproject.toml
├── src/
│   ├── main.py             # PyWebView 入口
│   ├── api.py              # JS Bridge + 后台 Agent 线程管理
│   ├── agent.py            # Agent 主循环(OpenAI 协议)
│   ├── event_bus.py        # 后端事件推前端
│   ├── tron_client.py      # TronScan REST 封装(6 个端点)
│   ├── tools/              # Agent 工具定义 + 执行器
│   ├── memory/graph.py     # 地址关系图 + Mermaid 生成
│   └── prompts/system.md   # Agent 的系统提示词
└── frontend/
    ├── index.html          # 启动屏 / 分析屏 / 报告屏
    ├── styles.css          # 赛博朋克主题
    └── app.js              # 视图切换 + 事件渲染 + Mermaid
```

---

## Agent 工具

| 工具 | 用途 |
|---|---|
| `analyze_address` | 查账户基础信息 + 风控标签(综合) |
| `get_address_transactions` | 查 TRX / TRC20 转账历史 |
| `analyze_token` | 查代币安全等级、红/灰/VIP 标签 |
| `mark_branch_complete` | 标记某分支追溯完毕 |
| `record_finding` | 记录关键发现(进入最终报告) |
| `request_user_decision` | 触发 UI 暂停,让用户决定继续/结束 |

---

## 安全声明

- **不存储任何私钥、助记词**
- **不签名任何交易** —— 纯查询工具
- **API Key 只存本机 `.env`**,`.env` 已在 `.gitignore`
- **不上传任何链上地址到第三方** —— 数据仅在 TronScan(查询) ↔ DeepSeek(分析) 间流转

报告结论**仅供参考,不构成法律或投资建议**。

---

## 致谢

- [DeepSeek](https://www.deepseek.com) — AI 推理引擎
- [TronScan](https://tronscan.org) — 链上数据
- [PyWebView](https://pywebview.flowrl.com) — 桌面窗口

---

**© GWCAPITAL · Research Division**
