"use strict";
// The conversation view: a window onto a long list of messages.
//
// Only a window of the messages exists as page elements (at most MAX_MOUNTED). The rest are kept as plain text in a list and
// stand in the page as two empty spacers, as tall as the missing messages were. Scrolling towards either end brings messages
// back; scrolling away lets the far end go. Older messages that were never loaded are fetched a page at a time.
//
// While a reply is being written only one element changes (its text), at most once per frame. The view follows the newest
// text only while the person is at the bottom; scrolling up stops it, and a button brings them back.
//
// Everything that comes from the model or the server is put on the page as text, never as markup.

const Thread = (() => {
  const MAX_MOUNTED = 60;   // messages kept as page elements at once
  const STEP = 20;          // how many come back per step when scrolling
  const GAP = 12;           // the space between messages: it must equal the gap of #thread in app.css
  const GUESS = 90;         // height assumed for a message that has never been on screen
  const NEAR = 400;         // closer than this to an end (pixels): bring more back
  const STICK = 80;         // closer than this to the bottom: keep following new text
  const ANNOUNCE_MAX = 4000;
  const FENCE = "```printlab-project";

  let log, thread, topSpacer, bottomSpacer, note, jump, announcer, makeCard, fetchOlder;
  let entries = [], start = 0, end = 0;   // the mounted ones are entries[start, end)
  let stick = true, hasMore = false, oldestId = null, loading = false, failed = false, epoch = 0, frame = 0, lastTop = 0;
  const live = new Set();                 // replies still being written

  function el(tag, cls) {
    const node = document.createElement(tag);
    if (cls) node.className = cls;
    return node;
  }

  function init(options) {
    log = options.log; note = options.note; jump = options.jump; announcer = options.announce;
    makeCard = options.makeCard; fetchOlder = options.fetchOlder;
    thread = el("div"); thread.id = "thread";
    topSpacer = el("div", "spacer"); bottomSpacer = el("div", "spacer");
    topSpacer.setAttribute("aria-hidden", "true"); bottomSpacer.setAttribute("aria-hidden", "true");
    log.replaceChildren(thread);
    log.addEventListener("scroll", onScroll, { passive: true });
    jump.addEventListener("click", toEnd);
    reset();
  }

  function reset() {
    epoch += 1;
    entries = []; start = 0; end = 0; live.clear();
    stick = true; hasMore = false; oldestId = null; loading = false; failed = false;
    thread.replaceChildren(topSpacer, bottomSpacer);
    note.hidden = true;
    setSpacers();
    updateJump();
  }

  // ---- entries ----

  // One reply can hold proposal blocks; each becomes its own entry (a card) between the plain text around it.
  function toEntries(kind, text, id) {
    if (kind === "assistant" && text.includes(FENCE)) {
      const out = [];
      for (const part of Proposal.split(text)) {
        if (part.proposal) out.push({ kind: "proposal", proposal: part.proposal, id, h: GUESS, node: null, card: null });
        else if (part.text.trim()) out.push({ kind: "assistant", text: part.text.trim(), id, h: GUESS, node: null });
      }
      if (out.some((e) => e.kind === "proposal")) return out;
    }
    return [{ kind, text, id, h: GUESS, node: null }];
  }

  function mount(entry) {
    if (entry.kind === "proposal") {
      entry.card = entry.card || makeCard(entry.proposal); // a card keeps its own state (done, linked) across unmounting
      entry.node = entry.card;
    } else {
      const node = el("div", "msg " + entry.kind + (entry.live ? " streaming" : "") + (entry.cut ? " cut" : "") + (entry.fresh ? " fresh" : ""));
      node.textContent = entry.text; // never innerHTML: model and tool text are untrusted
      entry.node = node;
    }
    entry.fresh = false;
    return entry.node;
  }

  function unmount(entry) {
    const node = entry.node;
    if (!node) return;
    if (node.isConnected) entry.h = node.offsetHeight + GAP; // remember what it took, so a spacer can stand in for it
    node.remove();
    entry.node = null;
  }

  function measure(a, b) {
    for (let i = a; i < b; i++) if (entries[i].node) entries[i].h = entries[i].node.offsetHeight + GAP;
  }

  function sum(a, b) {
    let total = 0;
    for (let i = a; i < b; i++) total += entries[i].h;
    return total;
  }

  // A spacer stands in for the messages that are not mounted. The flex gap already adds GAP beside it, so one GAP less.
  function setSpacers() {
    topSpacer.hidden = start === 0;
    topSpacer.style.height = (start > 0 ? Math.max(0, sum(0, start) - GAP) : 0) + "px";
    bottomSpacer.hidden = end >= entries.length;
    bottomSpacer.style.height = (end < entries.length ? Math.max(0, sum(end, entries.length) - GAP) : 0) + "px";
  }

  // Run a change that adds or removes things above what the person is reading, and put the view back where it was.
  function keepSteady(change) {
    const anchor = start < end ? entries[start].node : null;
    const before = anchor ? anchor.getBoundingClientRect().top : 0;
    change();
    if (anchor && anchor.isConnected) log.scrollTop += anchor.getBoundingClientRect().top - before;
  }

  // ---- loading a conversation, adding to it ----

  function load(messages, more) {
    reset();
    hasMore = Boolean(more);
    if (messages.length) oldestId = messages[0].id;
    for (const m of messages) entries.push(...toEntries(m.role, m.content, m.id));
    end = entries.length;
    start = Math.max(0, end - MAX_MOUNTED);
    for (let i = start; i < end; i++) thread.insertBefore(mount(entries[i]), bottomSpacer);
    measure(start, end);
    setSpacers();
    scrollToBottom();
    schedule();
  }

  function push(list) {
    const first = entries.length;
    const tailMounted = end === first;
    entries.push(...list);
    if (tailMounted) {
      for (let i = first; i < entries.length; i++) thread.insertBefore(mount(entries[i]), bottomSpacer);
      end = entries.length;
      measure(first, end);
    }
    setSpacers();
    follow();
    updateJump();
    schedule();
  }

  // A message the person sends always brings them to the bottom, wherever they were reading.
  function add(kind, text) {
    if (kind === "user") toEnd();
    const list = toEntries(kind, text, null);
    for (const entry of list) entry.fresh = true;
    push(list);
  }

  // A reply that is being written. `append` adds a piece; `finish` replaces it with the whole reply (which is the truth,
  // pieces can be lost on the way); `cut` marks a reply that was stopped before it was whole.
  function beginStream() {
    const entry = { kind: "assistant", text: "", id: null, h: GUESS, node: null, live: true, fresh: true };
    live.add(entry);
    push([entry]);
    return {
      append(piece) { entry.text += piece; schedule(); },
      finish(full) { finish(entry, full, false); },
      cut() { finish(entry, undefined, true); },
    };
  }

  function setText(node, text) {
    const first = node.firstChild;
    if (first && first.nodeType === 3) first.data = text; else node.textContent = text;
  }

  function remove(entry) {
    const index = entries.indexOf(entry);
    if (index < 0) return;
    unmount(entry);
    entries.splice(index, 1);
    if (index < start) { start -= 1; end -= 1; } else if (index < end) end -= 1;
    setSpacers();
  }

  function finish(entry, full, cut) {
    live.delete(entry);
    entry.live = false;
    if (typeof full === "string") entry.text = full;
    if (!entry.text) { remove(entry); updateJump(); return; } // nothing was said: no empty bubble
    if (cut) entry.cut = true;
    const parts = cut ? [entry] : toEntries("assistant", entry.text, null);
    if (parts.some((p) => p.kind === "proposal")) {
      // the finished reply holds a proposal: the one element becomes text and cards
      const index = entries.indexOf(entry);
      const old = entry.node;
      entries.splice(index, 1, ...parts);
      const extra = parts.length - 1;
      if (index < start) { start += extra; end += extra; }
      else if (index < end) {
        end += extra;
        const ref = old ? old.nextSibling : bottomSpacer;
        for (const part of parts) thread.insertBefore(mount(part), ref);
        if (old) old.remove();
        measure(index, index + parts.length);
      }
      setSpacers();
    } else if (entry.node) {
      setText(entry.node, entry.text);
      entry.node.className = "msg assistant" + (entry.cut ? " cut" : "");
    }
    if (!cut) announcer.textContent = entry.text.slice(0, ANNOUNCE_MAX); // read out once, finished, not letter by letter
    follow();
    updateJump();
    schedule();
  }

  // ---- scrolling ----

  function scrollToBottom() { log.scrollTop = log.scrollHeight; lastTop = log.scrollTop; }

  // Follow the newest text, but only if the person has not scrolled up since we last did. Growing content never lowers scrollTop,
  // so a smaller value means they moved it. That is known at once, unlike the scroll event, which arrives a frame later.
  function follow() {
    if (!stick) return;
    if (log.scrollTop < lastTop - 2) { stick = false; updateJump(); return; }
    scrollToBottom();
  }

  function updateJump() { jump.hidden = stick && end === entries.length; }

  function toEnd() {
    if (end !== entries.length) {
      // the newest messages are not mounted: swap the window for them
      for (let i = start; i < end; i++) unmount(entries[i]);
      end = entries.length;
      start = Math.max(0, end - STEP * 2);
      for (let i = start; i < end; i++) thread.insertBefore(mount(entries[i]), bottomSpacer);
      measure(start, end);
      setSpacers();
    }
    stick = true;
    scrollToBottom();
    updateJump();
    schedule();
  }

  function onScroll() {
    stick = log.scrollHeight - log.scrollTop - log.clientHeight <= STICK;
    failed = false; // the person is scrolling: a failed fetch may be tried again
    updateJump();
    schedule();
  }

  function schedule() {
    if (!frame) frame = requestAnimationFrame(tick);
  }

  function tick() {
    frame = 0;
    for (const entry of live) if (entry.node) setText(entry.node, entry.text); // at most once per frame, however fast the text comes
    if (live.size) follow();
    if (log.clientHeight) check();
  }

  function check() {
    const fromTop = log.scrollTop;
    const fromBottom = log.scrollHeight - log.scrollTop - log.clientHeight;
    let moved = false;
    if (fromTop < NEAR) {
      if (start > 0) { mountAbove(Math.min(STEP, start)); moved = true; }
      else if (hasMore && !loading && !failed) fetchMore();
    }
    if (fromBottom < NEAR && end < entries.length) { mountBelow(); moved = true; }
    trim();
    if (moved) schedule(); // still near an end after that? bring more
  }

  function mountAbove(count) {
    keepSteady(() => {
      const anchor = start < end ? entries[start].node : bottomSpacer;
      let ref = anchor;
      for (let i = start - 1; i >= start - count; i--) ref = thread.insertBefore(mount(entries[i]), ref);
      start -= count;
      measure(start, start + count);
      setSpacers();
    });
  }

  function mountBelow() {
    const count = Math.min(STEP, entries.length - end);
    for (let i = end; i < end + count; i++) thread.insertBefore(mount(entries[i]), bottomSpacer);
    measure(end, end + count);
    end += count;
    setSpacers();
  }

  // Too many mounted: let go of the end the person is farther from, never anything near what they can see.
  function trim() {
    if (end - start <= MAX_MOUNTED) return;
    const view = log.getBoundingClientRect();
    const fromTop = log.scrollTop;
    const fromBottom = log.scrollHeight - log.scrollTop - log.clientHeight;
    if (fromBottom <= fromTop) {
      while (end - start > MAX_MOUNTED) {
        const node = entries[start].node;
        if (node && node.getBoundingClientRect().bottom > view.top - NEAR / 2) break;
        unmount(entries[start]); start += 1;
      }
    } else {
      while (end - start > MAX_MOUNTED) {
        const node = entries[end - 1].node;
        if (node && node.getBoundingClientRect().top < view.bottom + NEAR / 2) break;
        end -= 1; unmount(entries[end]);
      }
    }
    setSpacers();
  }

  // Older messages that were never loaded come from the server, a page at a time.
  async function fetchMore() {
    const mine = epoch;
    loading = true; note.hidden = false;
    try {
      const page = await fetchOlder(oldestId);
      if (mine !== epoch) return; // another conversation was opened meanwhile
      const fresh = [];
      for (const m of page.messages) fresh.push(...toEntries(m.role, m.content, m.id));
      hasMore = Boolean(page.has_more) && page.messages.length > 0;
      if (page.messages.length) oldestId = page.messages[0].id;
      if (fresh.length) {
        keepSteady(() => {
          entries.unshift(...fresh);
          start += fresh.length; end += fresh.length;
          setSpacers();
          mountAbove(Math.min(STEP, start));
        });
      }
      schedule();
    } catch (_) {
      if (mine === epoch) failed = true;
    } finally {
      if (mine === epoch) { loading = false; note.hidden = true; }
    }
  }

  return { init, reset, load, add, beginStream };
})();
