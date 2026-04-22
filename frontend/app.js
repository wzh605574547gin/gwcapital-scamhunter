// GWCAPITAL · SCAMHUNTER 前端主逻辑 — 启动屏 / 分析视图 / 事件流。

const TRON_ADDRESS_RE = /^T[1-9A-HJ-NP-Za-km-z]{33}$/;

const state = {
  toolCount: 0,
  findingCount: 0,
  analyzed: [],
  awaitingDecision: false,
  sessionEnded: false,
  lastMermaid: "",
  sessionId: null,
};

// ---------------- 工具 ----------------
const $ = (id) => document.getElementById(id);
const short = (a) => (a && a.length > 12 ? `${a.slice(0, 6)}…${a.slice(-4)}` : a || "");
const clip = (s, n = 180) => {
  s = String(s ?? "");
  return s.length > n ? s.slice(0, n) + "…" : s;
};

function show(id) { $(id).classList.remove("hidden"); }
function hide(id) { $(id).classList.add("hidden"); }

function escapeHtml(s) {
  return String(s ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;");
}

function setHomeStatus(msg, kind = "info") {
  const el = $("home-status");
  el.textContent = msg;
  el.style.color = {
    info: "var(--cy-text-faded)",
    ok:   "var(--cy-green)",
    err:  "var(--cy-red)",
  }[kind];
}

function setBadge(text, variant = "cyan") {
  const b = $("session-badge");
  b.textContent = text;
  const cls = {
    cyan:    "cy-badge",
    orange:  "cy-badge cy-badge-orange",
    green:   "cy-badge cy-badge-green",
    red:     "cy-badge cy-badge-red",
    magenta: "cy-badge cy-badge-magenta",
    dim:     "cy-badge cy-badge-dim",
  }[variant] || "cy-badge";
  b.className = cls;
}

// ---------------- 视图切换 ----------------
function showHome() {
  show("view-home");
  hide("view-analysis");
}

function showAnalysis(address, userContext) {
  hide("view-home");
  show("view-analysis");
  $("target-address").textContent = address;
  state.sessionId = Math.random().toString(36).slice(2, 8).toUpperCase();
  $("session-id").textContent = state.sessionId;
  resetAnalysisState();
  if (userContext && userContext.trim()) {
    $("user-context-display").textContent = userContext.trim();
    show("user-context-section");
  } else {
    hide("user-context-section");
  }
}

function resetAnalysisState() {
  state.toolCount = 0;
  state.findingCount = 0;
  state.analyzed = [];
  state.awaitingDecision = false;
  state.sessionEnded = false;
  $("log-stream").innerHTML = "";
  $("analyzed-list").innerHTML = "";
  $("analyzed-count").textContent = "0";
  $("tool-count").textContent = "0";
  $("finding-count").textContent = "0";
  $("sidebar-status").textContent = "TRACING…";
  $("mermaid-container").innerHTML =
    `<div style="color: var(--cy-text-faded); text-align: center; padding: 40px 0; letter-spacing: 0.15em;">— AWAITING DATA —</div>`;
  hide("decision-panel");
  setBadge("TRACING", "cyan");
}

// ---------------- 日志渲染 ----------------
function appendLog(html) {
  const wrap = document.createElement("div");
  wrap.innerHTML = html;
  const el = wrap.firstElementChild || wrap;
  $("log-stream").appendChild(el);
  $("log-stream").scrollTop = $("log-stream").scrollHeight;
}

function logThinking(text) {
  if (!text || !text.trim()) return;
  appendLog(`<div class="cy-log-thinking">${escapeHtml(text)}</div>`);
}

function logToolCall(name, args) {
  const argStr = clip(JSON.stringify(args || {}, null, 0), 100);
  appendLog(`<div class="cy-log-toolcall">${escapeHtml(name)}(${escapeHtml(argStr)})</div>`);
}

function logToolResult(name, result) {
  const resStr = clip(JSON.stringify(result || {}, null, 0), 200);
  const isErr = result && result.error;
  const cls = "cy-log-toolresult" + (isErr ? " err" : "");
  appendLog(`<div class="${cls}">${escapeHtml(name)} → ${escapeHtml(resStr)}</div>`);
}

function logPhaseSummary(data) {
  const md = window.marked ? marked.parse(data.summary_markdown || "") : escapeHtml(data.summary_markdown);
  const verdictBadge = {
    safe: "cy-badge-green",
    suspicious: "cy-badge-orange",
    high_risk: "cy-badge-magenta",
    confirmed_scam: "cy-badge-red",
  }[data.current_verdict] || "cy-badge";
  appendLog(
    `<div class="cy-phase-card">
       <div class="flex items-center gap-3 mb-3">
         <h3>◆ PHASE VERDICT</h3>
         <span class="cy-badge ${verdictBadge}">${escapeHtml(data.current_verdict)} · ${escapeHtml(data.confidence)}</span>
       </div>
       <div class="markdown-body">${md}</div>
     </div>`
  );
}

function logFinalReport(markdown) {
  const md = window.marked ? marked.parse(markdown || "") : escapeHtml(markdown);
  appendLog(
    `<div class="cy-report-card">
       <h3>◉ FINAL REPORT</h3>
       <div class="markdown-body">${md}</div>
     </div>`
  );
  renderFinalReportMermaid();
}

function logError(msg) {
  appendLog(`<div class="cy-log-error">⚠ ERROR · ${escapeHtml(msg)}</div>`);
}

function logInfo(msg) {
  appendLog(`<div class="cy-log-info">${escapeHtml(msg)}</div>`);
}

// ---------------- 侧边栏 ----------------
function renderSidebar(snapshot) {
  if (!snapshot) return;
  state.analyzed = snapshot.analyzed || [];
  $("analyzed-count").textContent = String(snapshot.stats.addresses_analyzed || 0);
  $("finding-count").textContent = String(snapshot.stats.findings || 0);

  const list = $("analyzed-list");
  list.innerHTML = "";
  for (const a of state.analyzed) {
    const li = document.createElement("li");
    let cls = "cy-addr";
    if ((a.risk_flags || []).length) cls += " cy-addr-risk";
    else if (a.branch_complete) cls += " cy-addr-done";

    const tag = a.public_tag
      ? `<span style="color: var(--cy-magenta); font-weight: 700;">[${escapeHtml(a.public_tag.slice(0, 12))}]</span> `
      : "";
    const flags = (a.risk_flags || []).length
      ? ` <span style="color: var(--cy-red);">⚠</span>`
      : "";
    const done = a.branch_complete
      ? ` <span style="color: var(--cy-green);">✓</span>`
      : "";
    li.className = cls;
    li.innerHTML = `${tag}${short(a.address)}${flags}${done}`;
    li.title = a.address;
    list.appendChild(li);
  }
}

// ---------------- Mermaid ----------------
async function renderMermaid(mermaidSource) {
  if (!mermaidSource || mermaidSource === state.lastMermaid) return;
  state.lastMermaid = mermaidSource;
  const container = $("mermaid-container");
  try {
    const id = "mm-" + Date.now();
    const { svg } = await mermaid.render(id, mermaidSource);
    container.innerHTML = svg;
  } catch (e) {
    container.innerHTML =
      `<div style="color: var(--cy-red); font-size: 11px;">MERMAID RENDER FAILED</div>
       <pre style="font-size: 10px; color: var(--cy-text-faded); white-space: pre-wrap;">${escapeHtml(mermaidSource)}</pre>`;
    console.error("mermaid error", e);
  }
}

async function renderFinalReportMermaid() {
  const blocks = document.querySelectorAll("#log-stream pre code.language-mermaid");
  for (const code of blocks) {
    const src = code.textContent;
    const pre = code.parentElement;
    try {
      const id = "mmf-" + Math.random().toString(36).slice(2);
      const { svg } = await mermaid.render(id, src);
      pre.outerHTML = `<div style="background: var(--cy-bg-panel); border: 1px solid var(--cy-border); padding: 12px; margin: 10px 0;">${svg}</div>`;
    } catch (e) {
      console.warn("final report mermaid failed", e);
    }
  }
}

// ---------------- 决策面板 ----------------
function showDecisionPanel() {
  state.awaitingDecision = true;
  show("decision-panel");
  setBadge("PAUSED · AWAITING USER", "orange");
  $("sidebar-status").textContent = "AWAITING USER";
}

function hideDecisionPanel() {
  state.awaitingDecision = false;
  hide("decision-panel");
}

async function onDecisionClick(choice) {
  if (!state.awaitingDecision) return;
  document.querySelectorAll(".decision-btn").forEach(b => b.disabled = true);
  try {
    const res = await window.pywebview.api.user_decision(choice);
    if (!res.ok) {
      logError("决策发送失败:" + (res.error || "unknown"));
    } else {
      const label = { continue: "CONTINUE", finish: "FINALIZE", quit: "ABORT" }[choice];
      logInfo(`USER CHOICE · ${label}`);
      hideDecisionPanel();
      if (choice === "quit") {
        setBadge("ABORTED", "dim");
        $("sidebar-status").textContent = "ABORTED";
      } else {
        setBadge(choice === "finish" ? "FINALIZING" : "TRACING", "cyan");
        $("sidebar-status").textContent = choice === "finish" ? "GENERATING REPORT…" : "TRACING…";
      }
    }
  } finally {
    document.querySelectorAll(".decision-btn").forEach(b => b.disabled = false);
  }
}

// ---------------- 事件入口(后端推过来) ----------------
window.__onAgentEvent = function(ev) {
  try {
    const { type, data } = ev;
    switch (type) {
      case "session_start":
        logInfo(`TRACE START · ${short(data.address)}`);
        break;
      case "thinking":
        logThinking(data.text);
        break;
      case "tool_call":
        state.toolCount += 1;
        $("tool-count").textContent = String(state.toolCount);
        logToolCall(data.name, data.args);
        break;
      case "tool_result":
        logToolResult(data.name, data.result);
        break;
      case "phase_summary":
        logPhaseSummary(data);
        showDecisionPanel();
        break;
      case "graph_snapshot":
        renderSidebar(data);
        renderMermaid(data.mermaid);
        break;
      case "final_report":
        logFinalReport(data.markdown);
        setBadge("REPORT READY", "green");
        $("sidebar-status").textContent = "REPORT READY";
        break;
      case "session_end": {
        state.sessionEnded = true;
        const label = {
          final_report: "COMPLETED",
          user_quit:    "USER ABORT",
          done:         "DONE",
          error:        "ERROR EXIT",
          crashed:      "CRASHED",
        }[data.reason] || `END · ${data.reason}`;
        setBadge(label, data.reason === "final_report" ? "green" : "dim");
        $("sidebar-status").textContent = label;
        logInfo(`SESSION END · ${label}`);
        break;
      }
      case "error":
        logError(data.message || "unknown");
        break;
      default:
        console.log("[agent_event] unknown type:", type, data);
    }
  } catch (e) {
    console.error("onAgentEvent failed", e, ev);
  }
};

// ---------------- 启动屏逻辑 ----------------
async function waitForBridge(timeoutMs = 5000) {
  const start = Date.now();
  while (Date.now() - start < timeoutMs) {
    if (window.pywebview && window.pywebview.api) return true;
    await new Promise(r => setTimeout(r, 50));
  }
  return false;
}

async function onStartClick() {
  const input = $("address-input");
  const ctxInput = $("context-input");
  const btn = $("start-button");
  const addr = (input.value || "").trim();
  const ctx = (ctxInput.value || "").trim();

  if (!TRON_ADDRESS_RE.test(addr)) {
    setHomeStatus("× INVALID ADDRESS · 应以 T 开头,共 34 位 base58", "err");
    return;
  }

  btn.disabled = true;
  setHomeStatus("▸ INITIALIZING…", "info");
  try {
    const res = await window.pywebview.api.start_analysis(addr, ctx);
    if (res && res.ok) {
      setHomeStatus("", "info");
      showAnalysis(addr, ctx);
    } else {
      setHomeStatus("× START FAILED · " + (res?.error || "unknown"), "err");
    }
  } catch (e) {
    setHomeStatus("× BACKEND ERR · " + (e?.message || e), "err");
  } finally {
    btn.disabled = false;
  }
}

// ---------------- 初始化 ----------------
window.addEventListener("DOMContentLoaded", async () => {
  // Mermaid 初始化(深色赛博风)
  if (window.mermaid) {
    mermaid.initialize({
      startOnLoad: false,
      theme: "base",
      securityLevel: "loose",
      themeVariables: {
        darkMode: true,
        background: "#07101e",
        primaryColor: "#122036",
        primaryTextColor: "#e8f0ff",
        primaryBorderColor: "#00f0ff",
        lineColor: "#00f0ff",
        secondaryColor: "#1a2942",
        tertiaryColor: "#07101e",
        textColor: "#e8f0ff",
        fontFamily: "'JetBrains Mono', monospace",
      },
    });
  }

  // 启动屏
  $("start-button").addEventListener("click", onStartClick);
  $("address-input").addEventListener("keydown", (e) => {
    if (e.key === "Enter") onStartClick();
  });
  const ctxEl = $("context-input");
  const ctxCount = $("context-count");
  if (ctxEl && ctxCount) {
    const update = () => ctxCount.textContent = String(ctxEl.value.length);
    ctxEl.addEventListener("input", update);
    update();
  }

  // 分析屏
  document.querySelectorAll(".decision-btn").forEach(btn => {
    btn.addEventListener("click", () => onDecisionClick(btn.dataset.choice));
  });
  $("back-home").addEventListener("click", () => {
    if (!state.sessionEnded && state.toolCount > 0) {
      if (!confirm("分析尚未结束,确定返回首页?(当前进度会丢失)")) return;
    }
    showHome();
    $("address-input").value = "";
    setHomeStatus("");
  });

  const bridgeOk = await waitForBridge();
  if (!bridgeOk) {
    setHomeStatus("× BRIDGE NOT READY · 请重启应用", "err");
  }
});
