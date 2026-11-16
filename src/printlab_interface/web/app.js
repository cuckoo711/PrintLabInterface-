"use strict";
// The admin token lives only in this variable. It is never written to storage, cookies, the URL or the DOM.
let token = "";
let currentSession = null;
let currentRun = null;
let abortController = null;

const $ = (id) => document.getElementById(id);

async function api(path, options = {}) {
  const response = await fetch(path, {
    ...options,
    headers: { "x-admin-token": token, "content-type": "application/json", ...(options.headers || {}) },
    cache: "no-store",
    credentials: "omit",
  });
  if (!response.ok) {
    let detail = response.statusText;
    try {
      const body = await response.json();
      detail = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail);
    } catch (_) { /* keep statusText */ }
    const error = new Error(detail);
    error.status = response.status;
    throw error;
  }
  return response.status === 204 ? null : response;
}

const json = async (path, options) => (await api(path, options)).json();

function addMessage(kind, text) {
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

$("gate-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  token = $("token").value.trim();
  $("token").value = "";
  const gateError = $("gate-error");
  gateError.hidden = true;
  try {
    await loadAgents();
    await loadSessions();
  } catch (error) {
    token = "";
    gateError.textContent = error.status === 401 ? "令牌不对。" : "连接失败：" + error.message;
    gateError.hidden = false;
    return;
  }
  $("gate").hidden = true;
  $("app").hidden = false;
  $("conn").textContent = "已连接";
  $("conn").classList.add("ok");
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
