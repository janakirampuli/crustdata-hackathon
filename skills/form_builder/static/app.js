// Console chrome shared by every reviewer page: theme switch, mobile rail, live studies + credits, copy buttons.
(() => {
  const root = document.documentElement;
  const store = {
    get: k => { try { return localStorage.getItem(k); } catch { return null; } },
    set: (k, v) => { try { v == null ? localStorage.removeItem(k) : localStorage.setItem(k, v); } catch { /* private mode */ } },
  };

  function applyTheme(choice) {
    if (choice === "light" || choice === "dark") root.dataset.theme = choice; else delete root.dataset.theme;
    document.querySelectorAll("[data-theme-set]").forEach(b =>
      b.setAttribute("aria-pressed", String(b.dataset.themeSet === (choice || "system"))));
  }
  applyTheme(store.get("theme"));
  window.setTheme = v => { store.set("theme", v); applyTheme(v); };
  window.toggleTheme = () => {
    const dark = root.dataset.theme ? root.dataset.theme === "dark" : matchMedia("(prefers-color-scheme: dark)").matches;
    window.setTheme(dark ? "light" : "dark");
  };
  document.addEventListener("click", e => {
    const t = e.target.closest("[data-theme-set]");
    if (t) { const v = t.dataset.themeSet === "system" ? null : t.dataset.themeSet; store.set("theme", v); applyTheme(v); }
    const shell = document.getElementById("shell");
    if (e.target.closest("[data-rail-open]")) shell?.classList.add("rail-open");
    if (e.target.closest("[data-rail-close]")) shell?.classList.remove("rail-open");
    const c = e.target.closest("[data-copy]");
    if (c) {
      const label = c.querySelector("span") || c, before = label.textContent;
      const done = ok => { label.textContent = ok ? "Copied" : "Press ⌘C"; setTimeout(() => label.textContent = before, 1400); };
      if (navigator.clipboard) navigator.clipboard.writeText(c.dataset.copy).then(() => done(true), () => done(false));
      else done(false);
    }
  });

  const esc = v => String(v ?? "").replace(/[&<>"']/g, ch => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"}[ch]));
  async function refreshRail() {
    try {
      const res = await fetch("/api/rail");
      if (!res.ok) return;
      const {surveys, credits} = await res.json();
      const list = document.querySelector("[data-rail-studies]");
      if (list) list.innerHTML = surveys.length ? surveys.slice(0, 8).map(s =>
        `<a class="study" href="/surveys/${esc(s.id)}" title="${esc(s.title)}"><span class="dot ${esc(s.tone)}"></span>` +
        `<span class="t">${esc(s.title)}</span><span class="n">${s.responses}/${s.invites}</span></a>`).join("")
        : `<div class="rail-empty">No surveys yet. The agent drafts one when you describe a study.</div>`;
      const count = document.querySelector("[data-rail-count]");
      if (count) count.textContent = surveys.length;
      const meter = document.querySelector("[data-rail-credits]");
      if (meter && typeof credits === "number") {
        meter.hidden = false;
        meter.querySelector("b").textContent = credits.toLocaleString(undefined, {maximumFractionDigits: 2});
      }
    } catch { /* rail stays server-rendered */ }
  }
  window.refreshRail = refreshRail;
  refreshRail();
})();


// ⌘K palette: jump to any page, survey tab, participant or saved chat, and switch theme.
(() => {
  const isMac = /Mac|iPhone|iPad/.test(navigator.platform);
  document.querySelectorAll("[data-kbd]").forEach(k => k.textContent = isMac ? "⌘K" : "Ctrl K");
  const esc = v => String(v ?? "").replace(/[&<>"']/g, ch => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"}[ch]));
  const icon = n => `<svg class="i" aria-hidden="true"><use href="/static/icons.svg#${n}"/></svg>`;
  const ago = iso => {
    const m = Math.round((Date.now() - new Date(iso)) / 60000);
    return m < 1 ? "now" : m < 60 ? `${m}m ago` : m < 1440 ? `${Math.round(m / 60)}h ago` : `${Math.round(m / 1440)}d ago`;
  };
  const GROUPS = ["Commands", "Pages", "Surveys", "Survey pages", "People", "Chats"];
  const COMMANDS = [
    {group: "Commands", icon: "plus", title: "New chat", href: "/chat?new=1", keys: "start research study"},
    {group: "Commands", icon: "moon", title: "Toggle theme", run: () => window.toggleTheme?.(), keys: "dark light mode appearance"},
    {group: "Commands", icon: "sun", title: "Theme: Light", run: () => window.setTheme?.("light"), keys: "appearance mode"},
    {group: "Commands", icon: "moon", title: "Theme: Dark", run: () => window.setTheme?.("dark"), keys: "appearance mode"},
    {group: "Commands", icon: "monitor", title: "Theme: Match system", run: () => window.setTheme?.(null), keys: "appearance mode auto"},
    {group: "Pages", icon: "message", title: "Research chat", href: "/chat", keys: "agent home"},
    {group: "Pages", icon: "clipboard", title: "Surveys", href: "/surveys", keys: "studies list"},
  ];

  let items = [], shown = [], sel = 0, scrim = null;

  async function load() {
    const [index, chats] = await Promise.all([
      fetch("/api/search-index").then(r => r.ok ? r.json() : null).catch(() => null),
      fetch("/api/threads").then(r => r.ok ? r.json() : null).catch(() => null),
    ]);
    const out = [...COMMANDS];
    for (const s of index?.surveys || []) {
      out.push({group: "Surveys", icon: "clipboard", title: s.title, sub: s.status_label, href: `/surveys/${s.id}`, keys: s.question});
      for (const [key, label] of index.tabs || [])
        out.push({group: "Survey pages", icon: "arrow-right", title: `${s.title} › ${label}`, href: `/surveys/${s.id}?tab=${key}`,
                  keys: label, queryOnly: true});
    }
    for (const p of index?.people || [])
      out.push({group: "People", icon: "user", title: p.name || "Unnamed", sub: [p.title, p.company].filter(Boolean).join(" · "),
                hint: p.survey, href: `/surveys/${p.survey_id}?tab=participants`, keys: p.state, queryOnly: true});
    for (const t of chats?.threads || [])
      out.push({group: "Chats", icon: "message", title: t.title, hint: ago(t.updated_at), href: `/chat?thread=${encodeURIComponent(t.id)}`});
    items = out;
  }

  function score(item, q, tokens) {
    const title = item.title.toLowerCase();
    const hay = `${title} ${item.sub || ""} ${item.hint || ""} ${item.keys || ""} ${item.group}`.toLowerCase();
    if (!tokens.every(t => hay.includes(t))) return -1;
    return (title.startsWith(q) ? 4 : 0) + tokens.filter(t => title.includes(t)).length * 2 + (title.includes(q) ? 1 : 0);
  }

  function render() {
    const q = scrim.querySelector("input").value.trim().toLowerCase();
    const tokens = q.split(/\s+/).filter(Boolean);
    const caps = q ? {} : {Surveys: 6, Chats: 5};
    shown = [];
    for (const g of GROUPS) {
      let rows = items.filter(i => i.group === g && (q || !i.queryOnly))
        .map(i => ({i, s: q ? score(i, q, tokens) : 0})).filter(r => r.s >= 0);
      if (q) rows.sort((a, b) => b.s - a.s);
      shown.push(...rows.slice(0, caps[g] ?? 8).map(r => r.i));
    }
    sel = Math.min(sel, Math.max(shown.length - 1, 0));
    const list = scrim.querySelector(".palette-list");
    if (!shown.length) { list.innerHTML = `<div class="palette-empty">No matches for “${esc(q)}”</div>`; return; }
    let html = "", group = "";
    shown.forEach((it, n) => {
      if (it.group !== group) { group = it.group; html += `<div class="palette-group label">${esc(group)}</div>`; }
      html += `<a class="palette-item" role="option" id="pal-${n}" data-n="${n}" aria-selected="${n === sel}" ${it.href ? `href="${esc(it.href)}"` : ""}>
        ${icon(it.icon)}<span class="t">${esc(it.title)}${it.sub ? `<small>${esc(it.sub)}</small>` : ""}</span>
        <span class="hint">${esc(it.hint || "")}</span></a>`;
    });
    list.innerHTML = html;
    list.querySelector(`[data-n="${sel}"]`)?.scrollIntoView({block: "nearest"});
  }

  function choose(n) {
    const it = shown[n];
    if (!it) return;
    close();
    if (it.run) it.run(); else location.href = it.href;
  }

  async function open() {
    if (scrim) return;
    scrim = document.createElement("div");
    scrim.className = "palette-scrim";
    scrim.innerHTML = `<div class="palette" role="dialog" aria-modal="true" aria-label="Search">
        <div class="palette-input">${icon("search")}<input type="text" placeholder="Search surveys, people, chats, or type a command…"
          aria-label="Search" aria-controls="palette-list" autocomplete="off" spellcheck="false"><kbd>Esc</kbd></div>
        <div class="palette-list" id="palette-list" role="listbox"><div class="palette-empty">Loading…</div></div>
        <div class="palette-foot"><span><kbd>↑</kbd> <kbd>↓</kbd> to move</span><span><kbd>Enter</kbd> to open</span><span><kbd>Esc</kbd> to close</span></div>
      </div>`;
    document.body.append(scrim);
    const input = scrim.querySelector("input");
    input.focus();
    input.addEventListener("input", () => { sel = 0; render(); });
    scrim.addEventListener("mousedown", e => { if (e.target === scrim) close(); });
    scrim.addEventListener("click", e => {
      const a = e.target.closest(".palette-item");
      if (a) { e.preventDefault(); choose(+a.dataset.n); }
    });
    scrim.addEventListener("mousemove", e => {
      const a = e.target.closest(".palette-item");
      if (a && +a.dataset.n !== sel) { sel = +a.dataset.n; scrim.querySelectorAll(".palette-item").forEach(x =>
        x.setAttribute("aria-selected", String(+x.dataset.n === sel))); }
    });
    sel = 0; items = [...COMMANDS]; render();
    await load();
    if (scrim) render();
  }

  function close() { scrim?.remove(); scrim = null; }

  document.addEventListener("keydown", e => {
    if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") { e.preventDefault(); scrim ? close() : open(); return; }
    if (!scrim) return;
    if (e.key === "Escape") { e.preventDefault(); close(); }
    else if (e.key === "ArrowDown" || e.key === "ArrowUp") {
      e.preventDefault();
      if (!shown.length) return;
      sel = (sel + (e.key === "ArrowDown" ? 1 : -1) + shown.length) % shown.length;
      scrim.querySelectorAll(".palette-item").forEach(x => x.setAttribute("aria-selected", String(+x.dataset.n === sel)));
      scrim.querySelector(`[data-n="${sel}"]`)?.scrollIntoView({block: "nearest"});
    } else if (e.key === "Enter") { e.preventDefault(); choose(sel); }
  });
  document.addEventListener("click", e => { if (e.target.closest("[data-palette-open]")) open(); });
})();
