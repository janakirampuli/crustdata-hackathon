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
