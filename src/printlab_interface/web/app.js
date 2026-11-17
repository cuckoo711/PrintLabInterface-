"use strict";
// Signing in is handled by login.js: a passphrase the person set, and a browser session the page cannot read.
let currentSession = null;
let currentRun = null;
let abortController = null;

const $ = (id) => document.getElementById(id);

// A draft handed over from the PrintLab workbench ("new idea"). It travels in the address fragment (#draft=...), which the
// browser never sends to a server and which is kept out of Referer headers. It is read once, removed from the address
// at once, kept only in this variable, and only ever put in the message box as plain text: never sent on its own.
const MAX_DRAFT = 2000;
let handedOverDraft = "";
(function takeDraft() {
  try {
    const match = /^#draft=(.*)$/.exec(location.hash);
    if (!match) return;
    const text = decodeURIComponent(match[1].replace(/\+/g, " "));
    // keep line breaks, drop every other control character, then cap the length
    handedOverDraft = Array.from(text).filter((c) => c === "\n" || c >= " ").join("").slice(0, MAX_DRAFT).trim();
  } catch (_) { handedOverDraft = ""; }
  history.replaceState(null, "", location.pathname);
})();

// The PrintLab workbench listens on port 8018 of the same machine. The host name is taken from this page so the link
// also works when the page was opened by another name for this machine. Set here, not in the HTML: the page allows no inline script.
$("to-printlab").href = `${location.protocol}//${location.hostname}:8018/`;

async function api(path, options = {}) {
  const response = await fetch(path, {
    ...options,
    headers: Login.headers(options.headers || {}),
    cache: "no-store",
    credentials: "same-origin",
  });
  if (!response.ok) {
    let detail = response.statusText;
    let existing;
    try {
      const body = await response.json();
      if (body.detail && typeof body.detail === "object" && typeof body.detail.message === "string") {
        detail = body.detail.message;
        existing = typeof body.detail.existing === "string" ? body.detail.existing : undefined;
      } else {
        detail = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail);
      }
    } catch (_) { /* keep statusText */ }
    const error = new Error(detail);
    error.status = response.status;
    if (existing) error.existing = existing;
    throw error;
  }
  return response.status === 204 ? null : response;
}

// Asks the server to create the project the person just confirmed. The server checks everything again.
async function createProject(fields) {
  return (await api("/api/projects", { method: "POST", body: JSON.stringify(fields) })).json();
}

const json = async (path, options) => (await api(path, options)).json();

function addMessage(kind, text) {
  if (kind === "assistant" && text.includes("```printlab-project")) {
    const parts = Proposal.split(text);
    if (parts.some((part) => part.proposal)) {
      let last = null;
      for (const part of parts) {
        if (part.proposal) {
          const card = Proposal.card(part.proposal, createProject);
          $("log").appendChild(card);
          last = card;
        } else if (part.text.trim()) {
          last = addMessage("assistant", part.text.trim());
        }
      }
      $("log").scrollTop = $("log").scrollHeight;
      return last;
    }
  }
  const node = document.createElement("div");
  node.className = "msg " + kind;
  node.textContent = text; // never innerHTML: model and tool text are untrusted
  const log = $("log");
  log.appendChild(node);
  log.scrollTop = log.scrollHeight;
  return node;
}

function setState(text, isError = false) {
  const state = $("state");
  state.textContent = text;
  state.className = isError ? "error" : "";
}

function setBusy(busy) {
  $("send").disabled = busy;
  // Cancel stays off until the server has told us the run id; clicking earlier would have nothing to cancel.
  $("cancel").disabled = true;
  $("new-session").disabled = busy;
}

async function loadAgents() {
  const agents = await json("/api/agents");
  const select = $("agent");
  select.replaceChildren();
  for (const agent of agents) {
    const option = document.createElement("option");
    option.value = agent.name;
    option.textContent = agent.degraded ? `${agent.name} (无效)` : agent.name;
    option.disabled = agent.degraded;
    select.appendChild(option);
  }
}

async function loadSessions() {
  const list = $("sessions");
  list.replaceChildren();
  for (const session of await json("/api/sessions?limit=50")) {
    const item = document.createElement("li");
    const button = document.createElement("button");
    button.type = "button";
    button.textContent = `${session.agent} · ${session.title}`;
    button.title = session.title;
    if (session.id === currentSession) button.setAttribute("aria-current", "true");
    button.addEventListener("click", () => openSession(session.id));
    item.appendChild(button);
    list.appendChild(item);
  }
}

async function openSession(id) {
  const data = await json("/api/sessions/" + encodeURIComponent(id));
  currentSession = id;
  $("log").replaceChildren();
  for (const message of data.messages) addMessage(message.role, message.content);
  if ([...$("agent").options].some((o) => o.value === data.agent)) $("agent").value = data.agent;
  await loadSessions();
}

async function newSession() {
  const created = await json("/api/sessions", { method: "POST", body: JSON.stringify({ agent: $("agent").value }) });
  currentSession = created.id;
  $("log").replaceChildren();
  await loadSessions();
}

// Minimal SSE reader: EventSource cannot send a custom header, so read the stream by hand.
async function* readEvents(response) {
  const reader = response.body.getReader();
  const decoder = new TextDecoder("utf-8");
  let buffer = "";
  for (;;) {
    const { value, done } = await reader.read();
    if (done) return;
    buffer += decoder.decode(value, { stream: true });
    let cut;
    while ((cut = buffer.indexOf("\n\n")) !== -1) {
      const block = buffer.slice(0, cut);
      buffer = buffer.slice(cut + 2);
      let name = "message";
      let data = "";
      for (const line of block.split("\n")) {
        if (line.startsWith("event: ")) name = line.slice(7);
        else if (line.startsWith("data: ")) data += line.slice(6);
      }
      try { yield [name, JSON.parse(data)]; } catch (_) { /* ignore a malformed block */ }
    }
  }
}

async function send(text) {
  if (!currentSession) await newSession();
  addMessage("user", text);
  setBusy(true);
  setState("运行中…");
  abortController = new AbortController();
  try {
    const body = { message: text };
    const model = $("model").value.trim();
    if (model) body.model = model;
    const response = await api(`/api/sessions/${encodeURIComponent(currentSession)}/run`, {
      method: "POST", body: JSON.stringify(body), signal: abortController.signal,
    });
    for await (const [name, data] of readEvents(response)) {
      if (name === "start") { currentRun = data.run_id; $("cancel").disabled = false; }
      else if (name === "tool_call") setState("调用工具：" + data.name);
      else if (name === "tool_result") addMessage("tool", `${data.name}：${data.refused ? "被拒绝" : data.ok ? "完成" : "失败"}`);
      else if (name === "text" && data.text) addMessage("assistant", data.text);
      else if (name === "end") {
        if (data.status === "done") setState(`完成（${data.turns} 轮，${data.tool_calls} 次工具调用，${(data.usage || {}).total_tokens || 0} tokens）`);
        else setState(`结束：${data.status}${data.error ? "（" + data.error + "）" : ""}`, data.status !== "cancelled");
      }
    }
  } catch (error) {
    if (error.name === "AbortError") setState("已断开");
    else { addMessage("error", "出错：" + error.message); setState("出错", true); }
  } finally {
    currentRun = null;
    abortController = null;
    setBusy(false);
    loadSessions().catch(() => {});
  }
}

async function cancel() {
  if (!currentRun) return;
  $("cancel").disabled = true;
  try { await api(`/api/runs/${encodeURIComponent(currentRun)}/cancel`, { method: "POST" }); setState("正在取消…"); }
  catch (error) { setState("取消失败：" + error.message, true); }
}

Login.start(async () => {
  try {
    await loadAgents();
    await loadSessions();
  } catch (error) {
    setState("连接失败：" + error.message, true);
    return;
  }
  $("app").hidden = false;
  $("logout").hidden = false;
  $("logout").addEventListener("click", () => Login.logout());
  loadWorkflows().then(loadRuns).catch((error) => setState("工作流列表加载失败：" + error.message, true));
  if (handedOverDraft) {
    const wanted = Array.from($("agent").options).find((o) => o.value === "project" && !o.disabled);
    if (wanted) $("agent").value = "project";
    $("message").value = handedOverDraft;
    $("message").focus();
    setState("已带入来自 PrintLab 的想法。检查后按 Ctrl+Enter 发送；不会自动发送。");
    handedOverDraft = "";
  }
});

$("composer").addEventListener("submit", (event) => {
  event.preventDefault();
  const text = $("message").value.trim();
  if (!text || $("send").disabled) return;
  $("message").value = "";
  send(text);
});
$("message").addEventListener("keydown", (event) => {
  if (event.key === "Enter" && (event.ctrlKey || event.metaKey)) $("composer").requestSubmit();
});
$("new-session").addEventListener("click", () => newSession().catch((e) => setState(e.message, true)));
$("cancel").addEventListener("click", cancel);

// ---- workflows ---------------------------------------------------------
let currentWorkflowRun = null;
let workflowBusy = false;

const STATUS_LABEL = {
  running: "运行中", waiting: "等你回答", blocked: "被阻塞", failed: "出错", finished: "已完成", stopped: "已停止", interrupted: "被中断",
};

function showChat(show) {
  $("chat").hidden = !show;
  $("wf-panel").hidden = show;
}

function requestId() {
  // 8-80 chars of [A-Za-z0-9_.:-]; a fresh one per click so a double click is the only way to replay it.
  const bytes = new Uint8Array(12);
  crypto.getRandomValues(bytes);
  return "web-" + Array.from(bytes, (b) => b.toString(16).padStart(2, "0")).join("");
}

async function loadWorkflows() {
  const select = $("wf-name");
  select.replaceChildren();
  for (const wf of await json("/api/workflows")) {
    const option = document.createElement("option");
    option.value = wf.name;
    option.textContent = wf.valid ? wf.name : `${wf.name} (无效)`;
    option.disabled = !wf.valid;
    select.appendChild(option);
  }
}

async function loadRuns() {
  const list = $("wf-runs");
  list.replaceChildren();
  for (const run of await json("/api/workflow-runs?limit=30")) {
    const item = document.createElement("li");
    const button = document.createElement("button");
    button.type = "button";
    button.textContent = `${run.workflow} · ${run.project || "-"} · ${STATUS_LABEL[run.status] || run.status}`;
    if (run.id === currentWorkflowRun) button.setAttribute("aria-current", "true");
    button.addEventListener("click", () => openRun(run.id));
    item.appendChild(button);
    list.appendChild(item);
  }
}

function renderRun(run) {
  currentWorkflowRun = run.id;
  showChat(false);
  const status = $("wf-status");
  status.replaceChildren();
  const badge = document.createElement("span");
  badge.className = "badge " + run.status;
  badge.textContent = STATUS_LABEL[run.status] || run.status;
  status.append(`${run.workflow} · ${run.project || "-"} · 阶段 ${run.stage} `, badge);
  $("wf-detail").textContent = run.detail || "";
  $("wf-detail").className = run.status === "blocked" || run.status === "failed" ? "error" : "";

  const asking = run.status === "waiting" && run.waiting_for;
  $("wf-ask").hidden = !asking;
  const shown = $("wf-shown");
  shown.replaceChildren();
  if (asking) {
    $("wf-question").textContent = run.waiting_for.question;
    for (const [key, value] of Object.entries(run.waiting_for.show || {})) shown.appendChild(outputBlock(key, value));
  }
  $("wf-retry").hidden = !(run.status === "blocked" || run.status === "interrupted");
  $("wf-stop").hidden = ["finished", "stopped"].includes(run.status);

  const outputs = $("wf-outputs");
  outputs.replaceChildren();
  for (const [key, value] of Object.entries(run.outputs || {})) outputs.appendChild(outputBlock(key, value));
}

function outputBlock(label, text) {
  const box = document.createElement("div");
  box.className = "wf-out";
  const title = document.createElement("strong");
  title.textContent = label;
  const body = document.createElement("pre");
  body.textContent = text; // untrusted: model text
  box.append(title, body);
  return box;
}

async function openRun(id) {
  renderRun(await json("/api/workflow-runs/" + encodeURIComponent(id)));
  await loadRuns();
}

async function workflowAction(fn) {
  if (workflowBusy) return;
  workflowBusy = true;
  for (const id of ["wf-start", "wf-yes", "wf-no", "wf-retry", "wf-stop"]) $(id).disabled = true;
  try {
    await fn();
  } catch (error) {
    $("wf-detail").textContent = "出错：" + error.message;
    $("wf-detail").className = "error";
    $("wf-panel").hidden = false;
    $("chat").hidden = true;
  } finally {
    workflowBusy = false;
    for (const id of ["wf-start", "wf-yes", "wf-no", "wf-retry", "wf-stop"]) $(id).disabled = false;
    loadRuns().catch(() => {});
  }
}

$("wf-start").addEventListener("click", () => workflowAction(async () => {
  const body = { workflow: $("wf-name").value, request_id: requestId(), project: $("wf-project").value.trim(), brief: $("wf-brief").value };
  const model = $("model").value.trim();
  if (model) body.model = model;
  renderRun(await json("/api/workflow-runs", { method: "POST", body: JSON.stringify(body) }));
}));
for (const [id, answer] of [["wf-yes", "yes"], ["wf-no", "no"]]) {
  $(id).addEventListener("click", () => workflowAction(async () => {
    renderRun(await json(`/api/workflow-runs/${encodeURIComponent(currentWorkflowRun)}/answer`, { method: "POST", body: JSON.stringify({ answer }) }));
  }));
}
$("wf-retry").addEventListener("click", () => workflowAction(async () => {
  renderRun(await json(`/api/workflow-runs/${encodeURIComponent(currentWorkflowRun)}/retry`, { method: "POST" }));
}));
$("wf-stop").addEventListener("click", () => workflowAction(async () => {
  renderRun(await json(`/api/workflow-runs/${encodeURIComponent(currentWorkflowRun)}/stop`, { method: "POST" }));
}));
$("wf-close").addEventListener("click", () => { showChat(true); currentWorkflowRun = null; });

