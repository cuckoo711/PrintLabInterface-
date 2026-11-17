"use strict";
// Shared by the chat page and the admin page. Handles the first-time passphrase, logging in, and the session.
// The passphrase is typed into a form and sent once; it is cleared from the field at once and never kept. The session is a
// cookie the page cannot read (HttpOnly), and the only value held in memory is the CSRF value that goes with it.

const Login = (() => {
  let csrf = "";
  const $ = (id) => document.getElementById(id);

  async function post(path, body) {
    const response = await fetch(path, {
      method: "POST", cache: "no-store", credentials: "same-origin",
      headers: { "content-type": "application/json" }, body: JSON.stringify(body || {}),
    });
    let data = {};
    try { data = await response.json(); } catch (_) { /* no body */ }
    if (!response.ok) {
      const detail = typeof data.detail === "string" ? data.detail : (response.status === 422 ? "输入不符合要求" : response.statusText);
      const error = new Error(detail);
      error.status = response.status;
      throw error;
    }
    return data;
  }

  async function state() {
    const response = await fetch("/api/auth/state", { cache: "no-store", credentials: "same-origin" });
    if (!response.ok) throw new Error("无法连接服务");
    return response.json();
  }

  function show(id, on) { $(id).hidden = !on; }
  function error(text) { const node = $("gate-error"); node.textContent = text || ""; node.hidden = !text; }

  // Lets the page call the API: same-origin cookie, plus the CSRF value for anything that changes data.
  function headers(extra = {}) {
    return { "content-type": "application/json", ...(csrf ? { "x-csrf-token": csrf } : {}), ...extra };
  }

  async function start(onReady) {
    const gate = $("gate");
    function enter(token) {
      csrf = token || csrf;
      gate.hidden = true;
      $("conn").textContent = "已连接";
      $("conn").classList.add("ok");
      onReady();
    }

    let current;
    try { current = await state(); } catch (e) { error(e.message); return; }
    if (current.logged_in) { enter(current.csrf); return; }

    show("setup", !current.passphrase_set);
    show("login", current.passphrase_set);
    if (current.locked_seconds) error(`尝试次数太多，请 ${current.locked_seconds} 秒后再试`);

    $("setup-form").addEventListener("submit", async (event) => {
      event.preventDefault();
      error("");
      const chosen = $("setup-pass").value;
      const again = $("setup-pass2").value;
      $("setup-pass").value = ""; $("setup-pass2").value = "";
      if (chosen && chosen !== again) { error("两次输入的口令不一样"); return; }
      try {
        const result = await post("/api/auth/setup", chosen ? { passphrase: chosen } : {});
        if (result.generated_passphrase) {
          // Shown once, here and nowhere else. The person is asked to keep it before going on.
          $("generated-value").textContent = result.generated_passphrase;
          show("setup", false); show("generated", true);
          $("generated-ok").addEventListener("click", () => { $("generated-value").textContent = ""; show("generated", false); enter(result.csrf); }, { once: true });
        } else {
          show("setup", false); enter(result.csrf);
        }
      } catch (e) { error(e.message); }
    });

    $("login-form").addEventListener("submit", async (event) => {
      event.preventDefault();
      error("");
      const value = $("login-pass").value;
      $("login-pass").value = "";
      try {
        const result = await post("/api/auth/login", { passphrase: value });
        show("login", false); enter(result.csrf);
      } catch (e) { error(e.message); }
    });
  }

  async function logout() {
    try { await fetch("/api/auth/logout", { method: "POST", credentials: "same-origin", headers: headers() }); } finally { location.reload(); }
  }

  return { start, headers, logout };
})();
