"use strict";
// A new-project proposal the assistant made, shown as a card with one button.
//
// The assistant can only WRITE a block of text in its reply. This file turns that block into a card and, when the person
// clicks, asks the server to create the project. Nothing in the reply decides what is called: the address is fixed in this
// file, the fields are checked again here and again on the server, and the reply text is only ever put on the page as text.
//
// The block looks like this (the assistant is told to write it, and nothing else is accepted):
//   ```printlab-project
//   {"name": "...", "kind": "functional", "brief": "..."}
//   ```

const Proposal = (() => {
  const FENCE = /```printlab-project[ \t]*\n([\s\S]*?)\n```/g;
  const NAME_MAX = 80;
  const BRIEF_MAX = 1500;
  const KINDS = { functional: "实用件", sculpture: "造型件" };
  const BAD_NAME = /[\u0000-\u001f\u007f<>|"`$\\]/;
  const seen = new Set();

  // Split a reply into plain text and proposals. A block that is malformed is left in the text, not guessed at.
  function split(text) {
    const parts = [];
    let last = 0;
    for (const match of text.matchAll(FENCE)) {
      const proposal = parse(match[1]);
      if (!proposal) continue;
      if (match.index > last) parts.push({ text: text.slice(last, match.index) });
      parts.push({ proposal });
      last = match.index + match[0].length;
    }
    if (last < text.length) parts.push({ text: text.slice(last) });
    return parts;
  }

  function parse(raw) {
    let data;
    try { data = JSON.parse(raw); } catch (_) { return null; }
    if (!data || typeof data !== "object" || Array.isArray(data)) return null;
    if (Object.keys(data).some((k) => !["name", "kind", "brief"].includes(k))) return null; // unknown fields: not a proposal
    const name = typeof data.name === "string" ? data.name.replace(/\s+/g, " ").trim() : "";
    const kind = data.kind === undefined ? "functional" : data.kind;
    const brief = data.brief === undefined ? "" : data.brief;
    if (!name || name.length > NAME_MAX || BAD_NAME.test(name) || name.startsWith("-")) return null;
    if (!(kind in KINDS)) return null;
    if (typeof brief !== "string" || brief.length > BRIEF_MAX) return null;
    return { name, kind, brief: brief.trim() };
  }

  // The id comes from the proposal's own content (nothing random), so the same proposal always has the same id: pressing the
  // button twice, or seeing the same card again after a reload, can only ever make one project. Two different proposals differ.
  function idFor(p) {
    const text = JSON.stringify([p.name, p.kind, p.brief]);
    let a = 2166136261, b = 5381;
    for (const c of text) {
      const code = c.codePointAt(0);
      a = Math.imul(a ^ code, 16777619) >>> 0;
      b = (Math.imul(b, 33) + code) >>> 0;
    }
    return "pr-" + a.toString(36) + b.toString(36) + "-" + text.length.toString(36);
  }

  function el(tag, cls, text) {
    const node = document.createElement(tag);
    if (cls) node.className = cls;
    if (text !== undefined) node.textContent = text; // text only, never markup
    return node;
  }

  function card(p, createProject) {
    const id = idFor(p);
    const root = el("div", "proposal");
    root.append(el("span", "eyebrow", "建议新建项目"), el("h3", "", p.name), el("span", "meta", KINDS[p.kind]));
    if (p.brief) root.append(el("p", "", p.brief));
    const note = el("p", "warn"); note.hidden = true;
    const button = el("button", "", "建这个项目");
    button.type = "button";
    const row = el("div", "row");
    row.append(button);
    root.append(row, note);

    button.addEventListener("click", async () => {
      button.disabled = true;
      note.hidden = true;
      try {
        let result;
        try {
          result = await createProject({ proposal_id: id, name: p.name, kind: p.kind, brief: p.brief, allow_same_name: false });
        } catch (error) {
          if (error.status === 409 && error.existing) {
            // A project with this name already exists. Ask; do not decide for the person.
            if (!window.confirm(`已经有一个叫“${p.name}”的项目（${error.existing}）。还要再建一个同名的吗？`)) {
              note.textContent = `没有新建。已有项目 ${error.existing}。`;
              note.hidden = false; button.disabled = false;
              return;
            }
            result = await createProject({ proposal_id: id, name: p.name, kind: p.kind, brief: p.brief, allow_same_name: true });
          } else { throw error; }
        }
        root.classList.add("finished");
        row.remove();
        const done = el("p", "done");
        done.append(document.createTextNode(`${result.created ? "已建好" : "之前已经建过"}：${result.project_id}。`));
        const link = el("a", "", "在 PrintLab 里打开");
        link.href = `${location.protocol}//${location.hostname}:8018/#/projects/${encodeURIComponent(result.project_id)}`;
        link.target = "_blank"; link.rel = "noreferrer";
        done.append(document.createTextNode(" "), link);
        root.append(done);
      } catch (error) {
        note.textContent = "没有建成：" + (error.message || "未知错误");
        note.hidden = false;
        button.disabled = false;
      }
    });
    return root;
  }

  return { split, parse, card };
})();
