"use strict";
// Signing in is handled by login.js: a passphrase the person set, and a browser session the page cannot read.
// Every piece of text from the server is put on the page with textContent, never as markup.

const $ = (id) => document.getElementById(id);

// The PrintLab workbench listens on port 8018 of the same machine. The host name is taken from this page so the link
// also works when the page was opened by another name for this machine. Set here, not in the HTML: the page allows no inline script.
$("to-printlab").href = `${location.protocol}//${location.hostname}:8018/`;

function el(tag, props = {}, ...children) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(props)) {
    if (key === "text") node.textContent = value;
    else if (key === "class") node.className = value;
    else if (key === "onclick") node.addEventListener("click", value);
    else if (value === true) node.setAttribute(key, "");
    else if (value !== false && value != null) node.setAttribute(key, String(value));
  }
  for (const child of children) node.append(child);
  return node;
}

async function api(path, options = {}) {
  const response = await fetch(path, {
    ...options,
    headers: Login.headers(options.headers || {}),
    cache: "no-store",
    credentials: "same-origin",
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
  return response;
}

const json = async (path, options) => (await api(path, options)).json();
const send = (method, path, body) => api(path, { method, body: body === undefined ? undefined : JSON.stringify(body) });

function notice(text, isError = false) {
  const node = $("notice");
  node.textContent = text;
  node.className = "notice" + (isError ? " error" : "");
}

async function guarded(action, okText) {
  try {
    await action();
    if (okText) notice(okText);
  } catch (error) {
    notice(error.message || "操作失败", true);
  }
}

function when(seconds) {
  return seconds ? new Date(seconds * 1000).toLocaleString() : "—";
}

// ---------------------------------------------------------------- providers
async function loadProviders() {
  const providers = await json("/api/providers");
  const box = $("providers");
  box.replaceChildren();
  const select = $("k-prefix");
  select.replaceChildren();
  if (!providers.length) box.append(el("p", { class: "hint", text: "还没有供应商。" }));
  for (const p of providers) {
    select.append(el("option", { value: p.prefix, text: p.prefix }));
    const keys = el("ul", { class: "plain" });
    for (const k of p.keys) {
      const flags = [k.disabled ? "已停用" : null, k.invalid ? "已判定无效" : null].filter(Boolean).join("，");
      keys.append(el("li", {},
        el("span", { text: `${k.label}  ${k.hint}  优先级 ${k.priority}${flags ? "  (" + flags + ")" : ""}` }),
        el("button", { type: "button", class: "quiet", text: "删除密钥", onclick: () => guarded(async () => {
          if (!confirm(`删除密钥“${k.label}”？此操作不可撤销。`)) return;
          await send("DELETE", `/api/providers/${encodeURIComponent(p.prefix)}/keys/${encodeURIComponent(k.id)}`);
          await loadProviders();
        }, "密钥已删除") })));
    }
    box.append(el("article", { class: "card" },
      el("h3", { text: `${p.prefix}  ·  ${p.name}` }),
      el("p", { class: "hint", text: `${p.kind}${p.api_base ? "  ·  " + p.api_base : ""}  ·  ${p.enabled ? "已启用" : "已停用"}  ·  ${p.keys.length} 个密钥` }),
      keys,
      el("div", { class: "row" },
        el("button", { type: "button", class: "quiet", text: p.enabled ? "停用" : "启用", onclick: () => guarded(async () => {
          await send("PATCH", `/api/providers/${encodeURIComponent(p.prefix)}`, { enabled: !p.enabled });
          await loadProviders();
        }) }),
        el("button", { type: "button", class: "quiet", text: "删除供应商", onclick: () => guarded(async () => {
          if (!confirm(`删除供应商“${p.prefix}”及其全部密钥？此操作不可撤销。`)) return;
          await send("DELETE", `/api/providers/${encodeURIComponent(p.prefix)}`);
          await loadProviders();
        }, "供应商已删除") }))));
  }
}

$("provider-form").addEventListener("submit", (event) => {
  event.preventDefault();
  guarded(async () => {
    const base = $("p-base").value.trim();
    await send("POST", "/api/providers", { prefix: $("p-prefix").value.trim(), name: $("p-name").value.trim(), kind: $("p-kind").value, api_base: base || null });
    $("provider-form").reset();
    await loadProviders();
  }, "供应商已添加");
});

$("key-form").addEventListener("submit", (event) => {
  event.preventDefault();
  guarded(async () => {
    const field = $("k-key");
    const value = field.value;
    field.value = ""; // clear at once; the secret is not kept in the page after it is sent
    await send("POST", `/api/providers/${encodeURIComponent($("k-prefix").value)}/keys`,
      { label: $("k-label").value.trim() || "key", api_key: value, priority: Number($("k-priority").value) || 100 });
    await loadProviders();
  }, "密钥已保存（之后不会再显示）");
});

// ---------------------------------------------------------------- schedules
function scheduleSummary(s) {
  const caps = s.kind === "agent" ? `次数 ${s.runs_done}/${s.max_runs}  ·  token ${s.tokens_used}/${s.max_total_tokens}` : `已跑 ${s.runs_done} 次（不调用模型）`;
  return `${s.kind}  ·  ${s.trigger}  ·  每 ${s.interval_s} 秒  ·  ${caps}  ·  上次 ${when(s.last_run_at)}  ·  ${s.last_status || "—"}`;
}

async function loadSchedules() {
  const state = await json("/api/scheduler");
  $("sched-global").textContent = state.enabled
    ? "调度器已开启（PLI_SCHEDULER=1）。只有被你启用的计划才会运行。"
    : "调度器是关闭的：没有任何计划会自动运行。要开启，用环境变量 PLI_SCHEDULER=1 重启服务。手动运行也被禁用。";
  const box = $("schedules");
  box.replaceChildren();
  if (!state.schedules.length) box.append(el("p", { class: "hint", text: "还没有计划。" }));
  for (const s of state.schedules) {
    box.append(el("article", { class: "card" },
      el("h3", { text: s.name }, el("span", { class: "badge " + (s.enabled ? "on" : "off"), text: s.enabled ? " 已启用" : " 已关闭" })),
      el("p", { class: "hint", text: scheduleSummary(s) }),
      s.kind === "agent" ? el("p", { class: "quote", text: `${s.agent}  ·  ${s.model || "（角色文件里的模型）"}\n${s.prompt}` }) : "",
      el("div", { class: "row" },
        el("button", { type: "button", class: "quiet", text: s.enabled ? "关闭" : "启用", onclick: () => guarded(async () => {
          await send("PATCH", `/api/schedules/${encodeURIComponent(s.id)}`, { enabled: !s.enabled });
          await loadSchedules();
        }) }),
        el("button", { type: "button", class: "quiet", text: "立即运行一次", disabled: !state.enabled, onclick: () => guarded(async () => {
          if (s.kind === "agent" && !confirm("这会调用模型，用掉你的额度。继续？")) return;
          const result = await (await send("POST", `/api/schedules/${encodeURIComponent(s.id)}/run`)).json();
          await loadSchedules();
          await loadMail();
          notice(result.ran ? "已运行一次，结果在信箱里" : "没有运行（已达上限，或另一个计划正在运行）");
        }) }),
        el("button", { type: "button", class: "quiet", text: "删除", onclick: () => guarded(async () => {
          if (!confirm(`删除计划“${s.name}”？`)) return;
          await send("DELETE", `/api/schedules/${encodeURIComponent(s.id)}`);
          await loadSchedules();
        }, "计划已删除") }))));
  }
}

function syncScheduleForm() {
  const agent = $("s-kind").value === "agent";
  for (const id of ["s-trigger", "s-agent", "s-model", "s-prompt", "s-runs", "s-tokens"]) {
    $(id).disabled = !agent;
    $(id).required = agent && ["s-agent", "s-prompt", "s-runs", "s-tokens"].includes(id);
  }
  $("s-interval").min = agent ? "900" : "60";
}
$("s-kind").addEventListener("change", syncScheduleForm);

$("sched-form").addEventListener("submit", (event) => {
  event.preventDefault();
  guarded(async () => {
    const agent = $("s-kind").value === "agent";
    const body = { name: $("s-name").value.trim(), kind: $("s-kind").value, interval_s: Number($("s-interval").value) };
    if (agent) {
      Object.assign(body, {
        trigger: $("s-trigger").value, agent: $("s-agent").value, model: $("s-model").value.trim(), prompt: $("s-prompt").value,
        max_runs: Number($("s-runs").value), max_total_tokens: Number($("s-tokens").value),
      });
    }
    await send("POST", "/api/schedules", body);
    $("sched-form").reset();
    syncScheduleForm();
    await loadSchedules();
  }, "计划已创建，状态是关闭。确认无误后再启用。");
});

// ---------------------------------------------------------------- mailbox
async function loadMail() {
  const data = await json("/api/mailbox?limit=100" + ($("mail-unread").checked ? "&unread=true" : ""));
  $("unread").textContent = String(data.unread);
  const box = $("mail");
  box.replaceChildren();
  if (!data.messages.length) box.append(el("p", { class: "hint", text: "没有消息。" }));
  for (const m of data.messages) {
    box.append(el("article", { class: "card" + (m.read_at ? " read" : "") },
      el("h3", { text: m.subject }, el("span", { class: "badge " + m.severity, text: " " + m.severity })),
      el("p", { class: "hint", text: `${when(m.at)}  ·  ${m.sender}  ·  ${m.kind}` }),
      el("pre", { text: m.body }),
      m.read_at ? "" : el("button", { type: "button", class: "quiet", text: "标为已读", onclick: () => guarded(async () => {
        await send("POST", `/api/mailbox/${m.id}/ack`);
        await loadMail();
      }) })));
  }
}
$("mail-refresh").addEventListener("click", () => guarded(loadMail));
$("mail-unread").addEventListener("change", () => guarded(loadMail));

// ---------------------------------------------------------------- roles, workflows
async function loadRoles() {
  const agents = await json("/api/agents");
  const box = $("agents");
  box.replaceChildren();
  const select = $("s-agent");
  select.replaceChildren();
  for (const a of agents) {
    if (!a.degraded) select.append(el("option", { value: a.name, text: a.name }));
    box.append(el("article", { class: "card" },
      el("h3", { text: a.name }, a.degraded ? el("span", { class: "badge error", text: " 无效" }) : ""),
      el("p", { class: "hint", text: `${a.description || "—"}  ·  模型 ${a.model || "（调用时指定）"}  ·  最多 ${a.max_turns} 轮` }),
      el("p", { text: "工具：" + (a.tools.length ? a.tools.join("、") : "无") }),
      a.problems.length ? el("p", { class: "error", text: a.problems.join("；") }) : ""));
  }
  const flows = await json("/api/workflows");
  const fbox = $("workflows");
  fbox.replaceChildren();
  for (const w of flows) {
    fbox.append(el("article", { class: "card" },
      el("h3", { text: w.name }, w.valid ? "" : el("span", { class: "badge error", text: " 无效" })),
      el("p", { class: "hint", text: w.description || "—" }),
      el("p", { text: "阶段：" + (w.stages.map((s) => `${s.id}(${s.kind})`).join(" → ") || "无") }),
      w.problems.length ? el("p", { class: "error", text: w.problems.join("；") }) : ""));
  }
}

// ---------------------------------------------------------------- audit and export
async function loadAudit() {
  const rows = await json("/api/audit?limit=100");
  const box = $("audit");
  box.replaceChildren();
  const table = el("table", {}, el("thead", {}, el("tr", {}, ...["时间", "谁", "动作", "对象", "结果", "说明"].map((h) => el("th", { scope: "col", text: h })))));
  const body = el("tbody");
  for (const r of rows) {
    body.append(el("tr", {}, el("td", { text: when(r.at) }), el("td", { text: r.actor }), el("td", { text: r.action }),
      el("td", { text: r.target }), el("td", { text: r.outcome }), el("td", { text: r.detail })));
  }
  table.append(body);
  box.append(table);
}
$("audit-refresh").addEventListener("click", () => guarded(loadAudit));

$("export").addEventListener("click", () => guarded(async () => {
  const blob = await (await api("/api/export")).blob();
  const url = URL.createObjectURL(blob);
  const link = el("a", { href: url, download: "printlab-interface-config.json" });
  document.body.append(link);
  link.click();
  link.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
  await loadAudit(); // the export itself is an audit entry; show it
}, "已导出。文件里没有任何密钥。"));

// ---------------------------------------------------------------- tabs and start
function showTab(name) {
  for (const section of document.querySelectorAll(".tab")) section.hidden = section.id !== "tab-" + name;
  for (const button of document.querySelectorAll("nav button")) button.setAttribute("aria-current", String(button.dataset.tab === name));
}
for (const button of document.querySelectorAll("nav button")) {
  button.addEventListener("click", () => {
    showTab(button.dataset.tab);
    const loaders = { providers: loadProviders, schedules: loadSchedules, mailbox: loadMail, roles: loadRoles, audit: loadAudit };
    guarded(loaders[button.dataset.tab]);
  });
}

Login.start(async () => {
  try {
    await json("/api/scheduler");
  } catch (error) {
    notice("连接失败：" + error.message, true);
    return;
  }
  $("admin").hidden = false;
  $("logout").hidden = false;
  $("logout").addEventListener("click", () => Login.logout());
  syncScheduleForm();
  await Promise.all([loadProviders(), loadRoles(), loadSchedules(), loadMail()]);
});
