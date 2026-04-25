const TRON_ADDRESS_RE = /^T[1-9A-HJ-NP-Za-km-z]{33}$/;
const STEP_LABELS = [
  "核对地址是否真实存在",
  "查找交易对手和异常转账",
  "生成风险结论和关系图",
];

const state = {
  toolCount: 0,
  findingCount: 0,
  analyzed: [],
  awaitingDecision: false,
  sessionEnded: false,
  lastMermaid: "",
  lastSnapshot: null,
  sessionId: null,
  progressStep: 0,
  logVisible: false,
  graphVisible: false,
  bridgeReady: false,
};

const $ = (id) => document.getElementById(id);

function show(id) {
  $(id).classList.remove("hidden");
}

function hide(id) {
  $(id).classList.add("hidden");
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;");
}

function clip(value, limit = 220) {
  const text = String(value ?? "");
  return text.length > limit ? `${text.slice(0, limit)}…` : text;
}

function countRiskAddresses(snapshot) {
  return (snapshot?.analyzed || []).filter((item) => (item.risk_flags || []).length > 0).length;
}

function setHomeStatus(message = "", kind = "info") {
  const el = $("home-status");
  el.textContent = message;
  el.style.color = {
    info: "var(--text-muted)",
    ok: "var(--success)",
    err: "var(--danger)",
  }[kind];
}

function setStartButtonState(disabled, label = "开始分析") {
  const button = $("start-button");
  button.disabled = disabled;
  button.textContent = label;
}

function setBadge(text, variant = "info") {
  const badge = $("session-badge");
  badge.textContent = text;
  badge.dataset.variant = {
    info: "info",
    warning: "warning",
    success: "success",
    danger: "danger",
    muted: "muted",
  }[variant] || "info";
}

function setAddressError(visible) {
  $("address-input").classList.toggle("has-error", visible);
  $("address-error").classList.toggle("hidden", !visible);
}

function updateAddressCount() {
  $("address-count").textContent = `${$("address-input").value.trim().length} / 34`;
}

function updateContextCount() {
  $("context-count").textContent = `${$("context-input").value.length} / 200`;
}

function resetPanelsForNewSession() {
  hide("decision-panel");
  hide("report-panel");
  hide("details-panel");
  hide("graph-panel");
  state.logVisible = false;
  state.graphVisible = false;
  state.lastSnapshot = null;
  $("toggle-log").setAttribute("aria-expanded", "false");
  $("toggle-log").textContent = "查看详情";
  $("final-report-content").innerHTML = "";
  $("log-stream").innerHTML = "";
  $("mermaid-container").innerHTML = '<div class="empty-graph">分析开始后，这里会显示关系图。</div>';
}

function updateProgress(step) {
  const safeStep = Math.max(0, Math.min(3, step));
  state.progressStep = safeStep;
  const percent = `${(safeStep / 3) * 100}%`;
  $("progress-bar-fill").style.width = percent;
  $("progress-caption").textContent = `已完成 ${safeStep} / 3 步`;
  $("progress-count-label").textContent = `已完成 ${safeStep} / 3 步`;
  $("time-estimate").textContent = safeStep >= 3 ? "即将完成" : safeStep === 2 ? "预计还需 1-2 分钟" : "预计还需 2-3 分钟";

  STEP_LABELS.forEach((_, index) => {
    const item = $(`step-${index + 1}-indicator`).parentElement;
    if (index < safeStep) {
      item.dataset.stepState = "done";
      $(`step-${index + 1}-indicator`).textContent = "✓";
    } else if (index === safeStep && safeStep < 3) {
      item.dataset.stepState = "active";
      $(`step-${index + 1}-indicator`).textContent = String(index + 1);
    } else {
      item.dataset.stepState = "pending";
      $(`step-${index + 1}-indicator`).textContent = String(index + 1);
    }
  });
}

function updateClueSummary() {
  const findings = state.findingCount;
  if (findings <= 0) {
    $("clue-summary").textContent = "目前还没有可疑线索，系统正在开始检查。";
    return;
  }
  $("clue-summary").textContent = `目前发现 ${findings} 个可疑线索，系统正在继续核实。`;
}

function appendLog(html) {
  const wrap = document.createElement("div");
  wrap.innerHTML = html;
  const node = wrap.firstElementChild || wrap;
  $("log-stream").appendChild(node);
  $("log-stream").scrollTop = $("log-stream").scrollHeight;
}

function logThinking(text) {
  if (!text || !text.trim()) return;
  appendLog(`<div class="cy-log-thinking">${escapeHtml(text)}</div>`);
}

function logToolCall(name, args) {
  const argStr = clip(JSON.stringify(args || {}, null, 0), 200);
  appendLog(`<div class="cy-log-toolcall">${escapeHtml(name)}(${escapeHtml(argStr)})</div>`);
}

function logToolResult(name, result) {
  const resultStr = clip(JSON.stringify(result || {}, null, 0), 280);
  const cls = result && result.error ? "cy-log-toolresult cy-log-error" : "cy-log-toolresult";
  appendLog(`<div class="${cls}">${escapeHtml(name)} → ${escapeHtml(resultStr)}</div>`);
}

function verdictLabel(verdict) {
  const map = {
    safe: "低风险",
    suspicious: "中风险",
    high_risk: "高风险",
    confirmed_scam: "高风险",
  };
  return map[verdict] || "需进一步判断";
}

function verdictVariant(verdict) {
  if (verdict === "safe") return "success";
  if (verdict === "suspicious") return "warning";
  if (verdict === "confirmed_scam" || verdict === "high_risk") return "danger";
  return "muted";
}

function logPhaseSummary(data) {
  const markdown = window.marked ? marked.parse(data.summary_markdown || "") : escapeHtml(data.summary_markdown || "");
  appendLog(
    `<div class="cy-phase-card">
       <div class="details-panel__header">
         <h3>阶段结论</h3>
         <span class="status-badge" data-variant="${verdictVariant(data.current_verdict)}">${escapeHtml(verdictLabel(data.current_verdict))} · ${escapeHtml(data.confidence || "待确认")}</span>
       </div>
       <div class="markdown-body">${markdown}</div>
     </div>`
  );
}

function logFinalReport(markdown) {
  const html = window.marked ? marked.parse(markdown || "") : escapeHtml(markdown || "");
  $("final-report-content").innerHTML = html;
  show("report-panel");
  appendLog(
    `<div class="cy-report-card">
       <h3>最终报告</h3>
       <div class="markdown-body">${html}</div>
     </div>`
  );
  renderFinalReportMermaid();
}

function logError(message) {
  appendLog(`<div class="cy-log-error">${escapeHtml(message)}</div>`);
}

function logInfo(message) {
  appendLog(`<div class="cy-log-info">${escapeHtml(message)}</div>`);
}

function buildDecisionCopy(snapshot) {
  const riskCount = countRiskAddresses(snapshot);
  const findings = Math.max(state.findingCount, riskCount, 1);
  const riskAddresses = riskCount > 0 ? `${riskCount} 个高风险地址` : `${Math.min(findings, 3)} 个可疑地址`;
  const headline = `这个地址近 7 天和 ${riskAddresses} 有频繁资金往来，建议继续深挖。`;
  const followup = findings >= 3
    ? "下一步会继续追查资金最终流向，预计再用 1 分钟。"
    : "下一步会补充核对更多资金流向，预计再用 1-2 分钟。";
  return { headline, followup };
}

function showDecisionPanel(snapshot) {
  state.awaitingDecision = true;
  const copy = buildDecisionCopy(snapshot);
  $("decision-panel").querySelector("h3").textContent = copy.headline;
  $("decision-followup").textContent = copy.followup;
  show("decision-panel");
  setBadge("等待你决定下一步", "warning");
}

function hideDecisionPanel() {
  state.awaitingDecision = false;
  hide("decision-panel");
}

function renderSnapshot(snapshot) {
  if (!snapshot) return;
  state.lastSnapshot = snapshot;
  state.analyzed = snapshot.analyzed || [];
  state.findingCount = snapshot.stats?.findings || state.findingCount;
  updateClueSummary();

  let step = 0;
  if ((snapshot.stats?.addresses_analyzed || 0) > 0) step = 1;
  if (state.findingCount > 0 || (snapshot.analyzed || []).length > 1) step = 2;
  if (state.sessionEnded) step = 3;
  updateProgress(step);
}

async function renderMermaid(source) {
  if (!source || source === state.lastMermaid) return;
  state.lastMermaid = source;
  show("graph-panel");
  state.graphVisible = true;
  try {
    const id = `mm-${Date.now()}`;
    const { svg } = await mermaid.render(id, source);
    $("mermaid-container").innerHTML = svg;
  } catch (error) {
    $("mermaid-container").innerHTML = `<div class="cy-log-error">关系图渲染失败，请稍后重试。</div>`;
    console.error("mermaid error", error);
  }
}

async function renderFinalReportMermaid() {
  const blocks = document.querySelectorAll("#final-report-content pre code.language-mermaid, #log-stream pre code.language-mermaid");
  for (const code of blocks) {
    try {
      const id = `mmf-${Math.random().toString(36).slice(2)}`;
      const { svg } = await mermaid.render(id, code.textContent || "");
      code.parentElement.outerHTML = `<div class="mermaid-container">${svg}</div>`;
    } catch (error) {
      console.warn("final report mermaid failed", error);
    }
  }
}

async function onDecisionClick(choice) {
  if (!state.awaitingDecision) return;
  document.querySelectorAll(".decision-btn").forEach((button) => {
    button.disabled = true;
  });
  try {
    const response = await window.pywebview.api.user_decision(choice);
    if (!response.ok) {
      logError(`决策发送失败：${response.error || "未知错误"}`);
      return;
    }
    hideDecisionPanel();
    if (choice === "quit") {
      setBadge("分析已停止", "muted");
      state.sessionEnded = true;
      updateProgress(2);
      return;
    }
    setBadge(choice === "finish" ? "正在整理报告" : "继续分析中", "info");
    logInfo(choice === "finish" ? "你选择了先生成报告，系统正在整理当前发现。" : "你选择了继续深挖，系统正在追查下一层资金流向。");
  } finally {
    document.querySelectorAll(".decision-btn").forEach((button) => {
      button.disabled = false;
    });
  }
}

async function returnHome() {
  if (!state.sessionEnded && state.sessionId) {
    const confirmed = window.confirm("返回首页后，本次分析进度会丢失。确定现在结束并返回首页吗？");
    if (!confirmed) return;
    if (window.pywebview?.api?.cancel_analysis) {
      const result = await window.pywebview.api.cancel_analysis();
      if (!result?.ok) {
        logError(result?.error || "终止分析失败，请稍后重试。");
        setBadge("终止失败", "danger");
        return;
      }
    }
  }
  show("view-home");
  hide("view-analysis");
  $("address-input").value = "";
  $("context-input").value = "";
  updateAddressCount();
  updateContextCount();
  setAddressError(false);
  setHomeStatus("已终止本次分析，你可以重新输入地址开始新的检查。", "ok");
  if (!state.bridgeReady) {
    setStartButtonState(true, "等待应用连接");
  } else {
    setStartButtonState(false, "开始分析");
  }
  state.toolCount = 0;
  state.findingCount = 0;
  state.analyzed = [];
  state.awaitingDecision = false;
  state.sessionEnded = true;
  state.lastMermaid = "";
  state.lastSnapshot = null;
  state.sessionId = null;
  $("session-id").textContent = "-";
}

function showAnalysis(address) {
  hide("view-home");
  show("view-analysis");
  resetPanelsForNewSession();
  state.toolCount = 0;
  state.findingCount = 0;
  state.analyzed = [];
  state.awaitingDecision = false;
  state.sessionEnded = false;
  state.lastMermaid = "";
  state.lastSnapshot = null;
  state.sessionId = Math.random().toString(36).slice(2, 8).toUpperCase();
  $("session-id").textContent = state.sessionId;
  $("progress-caption").textContent = "已完成 0 / 3 步";
  updateProgress(0);
  updateClueSummary();
  setBadge("分析准备中", "info");
  logInfo(`已开始分析地址：${address}`);
}

window.__onAgentEvent = function onAgentEvent(event) {
  try {
    const { type, data } = event;
    switch (type) {
      case "session_start":
        updateProgress(1);
        setBadge("正在分析", "info");
        logInfo("系统正在核对地址是否真实存在。");
        break;
      case "thinking":
        logThinking(data.text);
        break;
      case "tool_call":
        state.toolCount += 1;
        if (state.toolCount >= 2) updateProgress(Math.max(state.progressStep, 2));
        logToolCall(data.name, data.args);
        break;
      case "tool_result":
        logToolResult(data.name, data.result);
        break;
      case "graph_snapshot":
        renderSnapshot(data);
        renderMermaid(data.mermaid);
        break;
      case "phase_summary":
        updateProgress(2);
        logPhaseSummary(data);
        showDecisionPanel(state.lastSnapshot || data.snapshot || null);
        break;
      case "final_report":
        state.sessionEnded = true;
        updateProgress(3);
        setBadge("报告已生成", "success");
        logFinalReport(data.markdown);
        break;
      case "session_end": {
        state.sessionEnded = true;
        const reason = data.reason;
        if (reason === "error" || reason === "crashed") {
          setBadge("分析出现异常", "danger");
        } else if (reason === "user_quit" || reason === "user_cancelled") {
          setBadge("分析已停止", "muted");
        } else {
          setBadge("分析已完成", "success");
          updateProgress(3);
        }
        logInfo(
          {
            final_report: "分析完成，你可以查看报告和关系图。",
            user_quit: "你已停止本次分析。",
            user_cancelled: "你已返回首页，本次分析已结束。",
            done: "分析结束。",
            error: "分析过程中出现异常，请稍后重试。",
            crashed: "分析过程中出现异常，请稍后重试。",
          }[reason] || `分析已结束：${reason}`
        );
        break;
      }
      case "error":
        logError(data.message || "分析过程中发生异常，请稍后重试。");
        setBadge("分析出现异常", "danger");
        break;
      default:
        console.log("unknown event", event);
    }
  } catch (error) {
    console.error("onAgentEvent failed", error, event);
  }
};

async function waitForBridge(timeoutMs = 5000) {
  const start = Date.now();
  while (Date.now() - start < timeoutMs) {
    if (window.pywebview && window.pywebview.api) return true;
    await new Promise((resolve) => setTimeout(resolve, 50));
  }
  return false;
}

async function onStartClick() {
  const address = $("address-input").value.trim();
  const context = $("context-input").value.trim();

  if (!state.bridgeReady || !window.pywebview?.api?.start_analysis) {
    setHomeStatus("应用连接尚未完成，开始分析按钮会在初始化完成后自动恢复。", "err");
    setStartButtonState(true, "等待应用连接");
    return;
  }

  if (!TRON_ADDRESS_RE.test(address)) {
    setAddressError(true);
    setHomeStatus("请输入正确的 TRON 地址后再开始分析。", "err");
    return;
  }

  setAddressError(false);
  setStartButtonState(true, "正在启动分析");
  setHomeStatus("正在准备分析，请稍等。", "info");
  try {
    const response = await window.pywebview.api.start_analysis(address, context);
    if (response && response.ok) {
      setHomeStatus("");
      showAnalysis(address);
    } else {
      setHomeStatus(response?.error || "分析启动失败，请稍后重试。", "err");
    }
  } catch (error) {
    setHomeStatus(`分析启动失败：${error?.message || error}`, "err");
  } finally {
    setStartButtonState(false, "开始分析");
  }
}

async function initializeBridge() {
  setStartButtonState(true, "等待应用连接");
  setHomeStatus("正在连接桌面分析服务，连接完成后才可以开始分析。", "info");
  const bridgeReady = await waitForBridge();
  if (!bridgeReady) {
    state.bridgeReady = false;
    setHomeStatus("应用连接未准备好，请重启应用后重试。", "err");
    setStartButtonState(true, "等待应用连接");
    return;
  }

  try {
    const response = await window.pywebview.api.ping("frontend-ready");
    if (!response?.ok) {
      throw new Error(response?.error || "ping 失败");
    }
    state.bridgeReady = true;
    setHomeStatus("应用已连接，可以开始分析。", "ok");
    setStartButtonState(false, "开始分析");
  } catch (error) {
    state.bridgeReady = false;
    setHomeStatus(`应用连接未准备好：${error?.message || error}`, "err");
    setStartButtonState(true, "等待应用连接");
  }
}

window.addEventListener("DOMContentLoaded", async () => {
  if (window.mermaid) {
    mermaid.initialize({
      startOnLoad: false,
      theme: "base",
      securityLevel: "loose",
      themeVariables: {
        background: "#fbfcfe",
        primaryColor: "#eaf2ff",
        primaryTextColor: "#1f2937",
        primaryBorderColor: "#93c5fd",
        lineColor: "#2563eb",
        secondaryColor: "#fffdf9",
        tertiaryColor: "#f8fafc",
        textColor: "#1f2937",
        fontFamily: "'Noto Sans SC', sans-serif",
      },
    });
  }

  $("start-button").addEventListener("click", onStartClick);
  $("address-input").addEventListener("input", () => {
    updateAddressCount();
    if ($("address-error").classList.contains("hidden")) return;
    if (TRON_ADDRESS_RE.test($("address-input").value.trim())) {
      setAddressError(false);
      setHomeStatus("");
    }
  });
  $("address-input").addEventListener("keydown", (event) => {
    if (event.key === "Enter") onStartClick();
  });
  $("context-input").addEventListener("input", updateContextCount);
  $("back-home").addEventListener("click", returnHome);
  $("toggle-log").addEventListener("click", () => {
    state.logVisible = !state.logVisible;
    $("toggle-log").setAttribute("aria-expanded", String(state.logVisible));
    $("toggle-log").textContent = state.logVisible ? "收起详情" : "查看详情";
    $("details-panel").classList.toggle("hidden", !state.logVisible);
  });
  $("toggle-graph").addEventListener("click", () => {
    state.graphVisible = true;
    show("graph-panel");
  });
  $("hide-graph").addEventListener("click", () => {
    state.graphVisible = false;
    hide("graph-panel");
  });
  document.querySelectorAll(".decision-btn").forEach((button) => {
    button.addEventListener("click", () => onDecisionClick(button.dataset.choice));
  });

  updateAddressCount();
  updateContextCount();
  updateProgress(0);
  updateClueSummary();
  await initializeBridge();
});
