// Research chat: streams agent turns over SSE and renders tool calls as a run log.
const $ = (sel, el = document) => el.querySelector(sel);
const log = $("#log"), scroller = $("#scroll"), input = $("#input"), send = $("#send");

const TOOLS = {
  crustdata_search_people: ["People search", "users"], crustdata_enrich_person: ["Profile enrich", "user"],
  crustdata_enrich_contact: ["Business email lookup", "mail"], crustdata_identify_company: ["Company identify", "building"],
  crustdata_search_companies: ["Company search", "building"], crustdata_search_jobs: ["Job search", "briefcase"],
  crustdata_get_credits: ["Credit balance", "coins"],
  form_create_survey: ["Survey draft", "file"], form_revise_survey: ["Survey revision", "file"],
  form_get_survey: ["Survey status", "clipboard"], form_list_surveys: ["Surveys", "clipboard"],
  form_create_invite_links: ["Invite links", "link"], form_get_responses: ["Responses", "inbox"],
  web_search: ["Web search", "globe"],
};
const STATUS = {draft: ["Draft", ""], changes_requested: ["Changes requested", "warn"], approved: ["Approved", "ok"], closed: ["Closed", ""]};
const VERIFIED = {pending: ["Pending", ""], ok: ["Verified", "ok"], flag: ["Flagged", "warn"], fail: ["Failed", "bad"]};

function storage(fn) { try { return fn(window.localStorage); } catch { return null; } }
function newId() { return (crypto.randomUUID && crypto.randomUUID()) || String(Date.now()) + Math.random(); }
let threadId = storage(s => s.getItem("threadId")) || newId();
storage(s => s.setItem("threadId", threadId));
const showThread = () => $("#thread-label").textContent = "thread " + threadId.slice(0, 8);

const esc = v => String(v ?? "").replace(/[&<>"']/g, c => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"}[c]));
const fmt = n => typeof n === "number" ? n.toLocaleString() : esc(n);
const icon = (name, cls = "") => `<svg class="i ${cls}" aria-hidden="true"><use href="/static/icons.svg#${name}"/></svg>`;
const link = (href, text) => href ? `<a href="${esc(href)}" target="_blank" rel="noopener">${esc(text)}</a>` : esc(text);
const words = k => k.replace(/([a-z])([A-Z])/g, "$1 $2").replace(/_/g, " ").toLowerCase();
const pill = ([label, tone]) => `<span class="pill ${tone}">${esc(label)}</span>`;
const statusPill = s => pill(STATUS[s] || [words(s || ""), ""]);
const plural = (n, one, many) => `${fmt(n)} ${n === 1 ? one : many}`;

if (window.DOMPurify) DOMPurify.addHook("afterSanitizeAttributes", node => {
  if (node.tagName === "A") { node.setAttribute("target", "_blank"); node.setAttribute("rel", "noopener"); }
});
function markdown(text) {
  if (!window.marked || !window.DOMPurify) return `<p style="white-space:pre-wrap">${esc(text)}</p>`;
  const t = document.createElement("template");
  t.innerHTML = DOMPurify.sanitize(marked.parse(text, {gfm: true, breaks: true}));
  t.content.querySelectorAll("table").forEach(tb => {
    tb.classList.add("tbl");
    const wrap = document.createElement("div"); wrap.className = "tbl-wrap";
    tb.replaceWith(wrap); wrap.append(tb);
  });
  return t.innerHTML;
}

function nearBottom() { return scroller.scrollHeight - scroller.scrollTop - scroller.clientHeight < 140; }
function stick(fn) { const pin = nearBottom(); fn(); if (pin) scroller.scrollTop = scroller.scrollHeight; }

// ---- transcript ----
let current = null;            // assistant text block being streamed
const runs = {};               // tool_call id -> {el, started}

function append(el) { $(".intro", log)?.remove(); log.append(el); return el; }
function node(tag, cls, html = "") { const el = document.createElement(tag); el.className = cls; el.innerHTML = html; return el; }

function addUser(text) { flushText(); append(node("div", "msg-user", esc(text))); }

let renderQueued = false;
function addText(delta) {
  if (!current) current = {el: append(node("div", "msg-agent")), text: ""};
  current.text += delta;
  if (!renderQueued) {
    renderQueued = true;
    requestAnimationFrame(() => { renderQueued = false; if (current) stick(() => current.el.innerHTML = markdown(current.text)); });
  }
}
function flushText() { if (current) current.el.innerHTML = markdown(current.text); current = null; }

function runGroup() {
  const last = log.lastElementChild;
  return last?.classList.contains("runs") ? last : append(node("div", "runs"));
}

function addToolCall(ev, replay = false) {
  flushText();
  const [label, ic] = TOOLS[ev.name] || [words(ev.name), "file"];
  const {caption, tags} = argsSummary(ev.name, ev.args || {});
  const el = node("details", "run running", `
    <summary>
      <span class="run-icon">${icon(ic)}</span>
      <span class="run-title"><b>${esc(label)}</b><span class="run-cap">${esc(caption)}</span></span>
      <span class="run-meta">${replay ? "" : "Running…"}</span>
      <span class="run-state">${icon("loader")}<span></span></span>
      ${icon("chevron-down")}
    </summary>
    <div class="run-body">${tags}</div>`);
  el.dataset.name = ev.name;
  el._args = ev.args || {};
  runGroup().append(el);
  runs[ev.id] = {el, started: replay ? null : performance.now()};
}

function addToolResult(ev) {
  if (!runs[ev.id]) addToolCall({id: ev.id, name: ev.name, args: {}}, true);
  const {el, started} = runs[ev.id];
  const c = ev.content, failed = c && typeof c === "object" && !Array.isArray(c) && c.error;
  el.classList.remove("running"); el.classList.add(failed ? "err" : "ok");
  $(".run-state", el).innerHTML = icon(failed ? "x-circle" : "check-circle") +
    `<span>${started ? ((performance.now() - started) / 1000).toFixed(1) + "s" : ""}</span>`;
  let meta = "Done", body = "", open = false;
  if (failed) { meta = "Error"; body = renderError(c); open = true; }
  else {
    const r = (RENDER[ev.name] || renderGeneric)(c);
    meta = r.meta ?? meta; body = r.body ?? ""; open = !!r.open;
    if (CANVAS_TOOLS.has(ev.name) && c?.survey_id) { addCanvas(c.survey_id); open = false; }
  }
  $(".run-meta", el).innerHTML = meta;
  const raw = `<details class="raw"><summary>Raw request and response</summary><pre class="log"></pre></details>`;
  $(".run-body", el).insertAdjacentHTML("beforeend", body + raw);
  $(".raw .log", el).textContent = "request\n" + JSON.stringify(el._args, null, 2) + "\n\nresponse\n" +
    (typeof c === "string" ? c : JSON.stringify(c, null, 2));
  if (open) {
    // Keep one auto-opened result at a time; rows the reader toggled stay as they left them.
    autoOpened.forEach(other => { if (other !== el && !other.dataset.touched) other.open = false; });
    autoOpened.add(el);
  }
  el.open = open;
  el.querySelector("summary").addEventListener("click", () => el.dataset.touched = "1");
}
const autoOpened = new Set();

function argsSummary(name, args) {
  const src = name === "crustdata_search_people" ? (args.plan || {}) : args;
  const entries = Object.entries(src).filter(([k, v]) => {
    if (v == null || v === "" || ["survey", "targets", "fields", "raw"].includes(k)) return false;
    return Array.isArray(v) ? v.length > 0 : true;
  });
  let caption = entries.map(([, v]) => chipValue(v)).join(" · ");
  if (args.survey?.title) caption = args.survey.title;
  if (args.targets) caption = plural(args.targets.length, "target", "targets");
  const tags = entries.length
    ? `<div class="tags">${entries.map(([k, v]) => `<span class="tag">${esc(words(k))} <b>${esc(chipValue(v))}</b></span>`).join("")}</div>` : "";
  return {caption, tags};
}
function chipValue(v) {
  if (Array.isArray(v)) return v.map(chipValue).join(", ");
  if (v && typeof v === "object") return Object.entries(v).filter(([, x]) => x != null).map(([k, x]) => `${words(k)} ${chipValue(x)}`).join(" · ");
  return String(v);
}

function renderError(c) {
  const extra = c.detail || c.message || c.body || c.feedback;
  const warnings = (c.warnings || []).map(w => `<li>${esc(w)}</li>`).join("");
  return `<div class="msg-error">${icon("alert")}<div><b>${esc(words(String(c.error)))}</b>${c.status ? ` · ${esc(c.status)}` : ""}
      ${extra ? `<div class="cap">${esc(typeof extra === "string" ? extra : JSON.stringify(extra))}</div>` : ""}</div></div>
    ${c.review_url ? `<a class="btn btn-sm" href="${esc(c.review_url)}" target="_blank" rel="noopener">${icon("external", "i-sm")} Open review page</a>` : ""}
    ${warnings ? `<ul class="warn-list">${warnings}</ul>` : ""}`;
}

function table(headers, rows) {
  return `<div class="tbl-wrap"><table class="tbl"><thead><tr>${headers.map(h => `<th>${h}</th>`).join("")}</tr></thead>
    <tbody>${rows.join("")}</tbody></table></div>`;
}
const copyBtn = text => `<button class="btn btn-sm" type="button" data-copy="${esc(text)}">${icon("copy", "i-sm")}<span>Copy</span></button>`;

const RENDER = {
  web_search(c) {
    const results = c.results || [];
    const host = u => { try { return new URL(u).hostname.replace(/^www\./, ""); } catch { return ""; } };
    const items = results.slice(0, 5).map(r => `<li>${link(r.url, r.title || r.url)}
      <span class="cap">${esc(host(r.url))}${r.page_age ? " · " + esc(r.page_age) : ""}</span></li>`);
    return {meta: plural(results.length, "result", "results"), body: items.length ? `<ul class="sources">${items.join("")}</ul>` : ""};
  },
  crustdata_search_people(c) {
    const people = c.profiles || [];
    const total = c.total_count == null ? "?" : fmt(c.total_count) + (c.total_count_relation === "gte" ? "+" : "");
    const rows = people.map((p, i) => `<tr>
      <td class="idx">${i + 1}</td>
      <td>${link(p.linkedin_url, p.name || "—")}${p.headline ? `<span class="sub">${esc(p.headline.slice(0, 70))}</span>` : ""}</td>
      <td>${esc(p.title)}${p.seniority ? `<span class="sub">${esc(p.seniority)}${p.function ? " · " + esc(p.function) : ""}</span>` : ""}</td>
      <td>${link(p.company_website, p.company || "—")}${p.company_headcount != null ? `<span class="sub">${fmt(p.company_headcount)} people</span>` : ""}</td>
      <td>${esc(p.location)}</td>
      <td>${p.has_business_email ? `<span class="yes" title="Business email on file">${icon("check-circle", "i-sm")}</span>` : '<span class="no">—</span>'}</td></tr>`);
    const warnings = (c.warnings || []).map(w => `<li>${esc(w)}</li>`).join("");
    return {
      open: true,
      meta: `${total} ${c.total_count === 1 ? "match" : "matches"} · ${fmt(people.length)} shown`,
      body: (people.length ? table(["#", "Name", "Title", "Company", "Location", "Email"], rows) : `<p class="cap">No profiles returned.</p>`)
        + (c.dropped_outside_person_countries ? `<p class="cap">${fmt(c.dropped_outside_person_countries)} dropped outside the requested countries.</p>` : "")
        + (c.next_cursor ? `<p class="cap">More results available on the next page.</p>` : "")
        + (warnings ? `<ul class="warn-list">${warnings}</ul>` : ""),
    };
  },
  crustdata_enrich_contact(c) {
    const people = c.people || [];
    const rows = people.map(p => {
      const slug = (p.linkedin_url || "").replace(/\/+$/, "").split("/").pop();
      const emails = (p.business_emails || []).map(e =>
        `<div>${esc(e.email)} ${pill([e.status || "unknown", e.status === "deliverable" ? "ok" : e.status === "invalid" ? "bad" : "warn"])}</div>`).join("")
        || `<span class="no">${esc(p.message || p.match_status || "No email found")}</span>`;
      return `<tr><td>${link(p.linkedin_url, slug || "profile")}</td><td>${emails}</td></tr>`;
    });
    const found = people.filter(p => (p.business_emails || []).length).length;
    return {
      open: true,
      meta: `${found} of ${fmt(people.length)} with email${c.mocked ? ` ${pill(["Mocked", "warn"])}` : ""}`,
      body: table(["Profile", "Business email"], rows),
    };
  },
  crustdata_get_credits(c) { return {meta: `${fmt(c.credits)} credits`}; },
  form_create_survey: renderSurvey, form_revise_survey: renderSurvey, form_get_survey: renderSurvey,
  form_list_surveys(c) {
    const rows = (c.surveys || []).map(s => `<tr><td>${link(s.review_url, s.title)}</td><td>${statusPill(s.status)}</td>
      <td class="mono">${fmt(s.responses)} / ${fmt(s.invites)}</td></tr>`);
    return {open: true, meta: plural((c.surveys || []).length, "survey", "surveys"),
            body: rows.length ? table(["Survey", "Status", "Responded / invited"], rows) : ""};
  },
  form_create_invite_links(c) {
    const links = c.links || [];
    const rows = links.map(l => `<tr><td>${esc(l.name)}<span class="sub">${esc(l.business_email || "no email")}</span></td>
      <td><div style="display:flex; gap:6px; flex-wrap:wrap">${link(l.url, "Open")} ${copyBtn(l.url)}</div>
        ${l.reused ? '<span class="sub">Existing link</span>' : ""}</td></tr>`);
    return {open: true, meta: plural(links.length, "link", "links"), body: table(["Person", "Personal link"], rows)};
  },
  form_get_responses(c) {
    const st = c.stats || {};
    const rows = (c.responses || []).map(r => `<tr><td>${esc(r.target?.name)}<span class="sub">${esc(r.target?.title || "")}</span></td>
      <td>${esc(r.target?.company)}</td><td>${pill(VERIFIED[r.verified] || [r.verified, ""])}</td>
      <td class="mono">${esc((r.submitted_at || "").slice(0, 16).replace("T", " "))}</td></tr>`);
    return {open: rows.length > 0, meta: `${fmt(st.responded ?? 0)} of ${fmt(st.invited ?? 0)} responded`,
            body: rows.length ? table(["Respondent", "Company", "Verification", "Submitted (UTC)"], rows) : ""};
  },
};

function renderSurvey(c) {
  const st = c.stats;
  return {
    open: true,
    meta: statusPill(c.status),
    body: `<div class="survey-card">
        <div class="grow"><b>${esc(c.survey?.title || "Survey " + (c.survey_id || ""))}</b>
          <span class="cap">${c.questions ? plural(c.questions, "question", "questions") + " · " : ""}<span class="mono">${esc(c.survey_id)}</span>
          ${st ? ` · ${fmt(st.invited)} invited · ${fmt(st.responded)} responded` : ""}</span></div>
        ${c.review_url ? `<a class="btn ${c.status === "approved" ? "" : "btn-primary"}" href="${esc(c.review_url)}" target="_blank" rel="noopener">
          ${c.status === "approved" ? "Open survey" : "Review and approve"} ${icon("external", "i-sm")}</a>` : ""}
      </div>
      ${c.feedback ? `<div class="msg-error" style="background:var(--warn-soft)">${icon("alert")}<div><b>Reviewer feedback</b><div>${esc(c.feedback)}</div></div></div>` : ""}`,
  };
}

// ---- approval canvas: the live survey, rendered server-side, with approve / request-changes actions ----
const CANVAS_TOOLS = new Set(["form_create_survey", "form_revise_survey"]);

function addCanvas(surveyId) {
  log.querySelectorAll(`.canvas[data-survey="${CSS.escape(surveyId)}"]`).forEach(el => el.remove());
  const el = append(node("section", "canvas", `<p class="cap">Loading survey…</p>`));
  el.dataset.survey = surveyId;
  loadCanvas(el);
}

async function loadCanvas(el) {
  try {
    const res = await fetch(`/api/surveys/${encodeURIComponent(el.dataset.survey)}/canvas`);
    const html = await res.text();
    if (el.dataset.html !== html) { el.dataset.html = html; el.innerHTML = html; }
  } catch { /* keep the last render */ }
  el.classList.toggle("locked", busy);
}
const refreshCanvases = () => log.querySelectorAll(".canvas").forEach(loadCanvas);

async function canvasPost(el, action, body) {
  const res = await fetch(`/surveys/${encodeURIComponent(el.dataset.survey)}/${action}`, {method: "POST", body});
  if (!res.ok) throw new Error(`The server returned ${res.status}.`);
  await loadCanvas(el);
}

log.addEventListener("click", async e => {
  const btn = e.target.closest("[data-canvas]"), el = btn?.closest(".canvas");
  if (!el || btn.tagName === "FORM") return;
  const title = $(".canvas-title b", el)?.textContent || "survey";
  if (btn.dataset.canvas === "toggle-changes") {
    const form = $("[data-canvas=changes]", el);
    form.hidden = !form.hidden;
    $(".canvas-foot > .canvas-actions", el).hidden = !form.hidden;
    if (!form.hidden) $("textarea", form).focus();
  } else if (btn.dataset.canvas === "approve" && !busy) {
    btn.disabled = true;
    try {
      await canvasPost(el, "approve");
      ask(`Approved the survey "${title}" (${el.dataset.survey}). Continue.`);
    } catch (err) { btn.disabled = false; handle({type: "error", message: String(err.message || err)}); }
  }
});

log.addEventListener("submit", async e => {
  const form = e.target.closest("[data-canvas=changes]"), el = form?.closest(".canvas");
  if (!el) return;
  e.preventDefault();
  const feedback = form.feedback.value.trim();
  if (!feedback || busy) return;
  const title = $(".canvas-title b", el)?.textContent || "survey";
  try {
    await canvasPost(el, "request-changes", new FormData(form));
    ask(`Requested changes on the survey "${title}" (${el.dataset.survey}):\n${feedback}`);
  } catch (err) { handle({type: "error", message: String(err.message || err)}); }
});

// Approvals made on the full review page show up when the reader comes back.
window.addEventListener("focus", () => { if (!busy) refreshCanvases(); });

function renderGeneric(c) {
  if (c && typeof c === "object" && !Array.isArray(c)) {
    const flat = Object.entries(c).filter(([, v]) => v === null || typeof v !== "object");
    if (flat.length && flat.length <= 4) return {meta: flat.map(([k, v]) => `${esc(words(k))} ${fmt(v)}`).join(" · ")};
  }
  return {};
}

function handle(ev, replay = false) {
  if (ev.type === "user") addUser(ev.text);
  else if (ev.type === "text") addText(ev.text);
  else if (ev.type === "tool_call") addToolCall(ev, replay);
  else if (ev.type === "tool_result") addToolResult(ev);
  else if (ev.type === "error") { flushText(); append(node("div", "msg-error", icon("alert") + `<div>${esc(ev.message)}</div>`)); }
}

// ---- turn lifecycle ----
let working = null;
function setWorking(on) {
  working?.remove(); working = null;
  if (on) stick(() => working = append(node("div", "working", icon("loader") + "<span>Working…</span>")));
}

let busy = false;
async function ask(text) {
  if (busy || !text.trim()) return;
  busy = true; send.disabled = true;
  log.querySelectorAll(".canvas").forEach(el => el.classList.add("locked"));
  stick(() => addUser(text));
  setWorking(true);
  try {
    const res = await fetch("/api/chat", {method: "POST", headers: {"Content-Type": "application/json"},
                                          body: JSON.stringify({thread_id: threadId, message: text})});
    if (!res.ok) throw new Error(`The server returned ${res.status}. ${await res.text()}`);
    const reader = res.body.getReader(), decoder = new TextDecoder();
    let buf = "";
    for (;;) {
      const {value, done} = await reader.read();
      if (done) break;
      buf += decoder.decode(value, {stream: true});
      let i;
      while ((i = buf.indexOf("\n\n")) >= 0) {
        const line = buf.slice(0, i); buf = buf.slice(i + 2);
        if (!line.startsWith("data: ")) continue;
        const ev = JSON.parse(line.slice(6));
        if (ev.type === "done") continue;
        working?.remove(); working = null;
        stick(() => handle(ev));
        if (ev.type === "tool_result") setWorking(true);
      }
    }
  } catch (err) {
    handle({type: "error", message: String(err.message || err)});
  } finally {
    flushText(); setWorking(false);
    busy = false; send.disabled = false; input.focus();
    window.refreshRail?.(); refreshCanvases();
  }
}

function showEmpty() {
  log.innerHTML = "";
  log.append($("#empty").content.cloneNode(true));
  log.querySelectorAll("[data-prompt]").forEach(b => b.addEventListener("click", () => ask(b.dataset.prompt)));
}

async function restore() {
  showEmpty(); showThread();
  try {
    const res = await fetch(`/api/threads/${encodeURIComponent(threadId)}`);
    const {events} = await res.json();
    events.forEach(ev => handle(ev, true)); flushText();
    if (events.length) scroller.scrollTop = scroller.scrollHeight;
  } catch { /* fresh thread */ }
}

$("#composer").addEventListener("submit", e => {
  e.preventDefault();
  const text = input.value; input.value = ""; grow(); ask(text);
});
input.addEventListener("keydown", e => {
  if (e.key === "Enter" && !e.shiftKey && !e.isComposing) { e.preventDefault(); $("#composer").requestSubmit(); }
});
function grow() { input.style.height = "auto"; input.style.height = Math.min(input.scrollHeight, 200) + "px"; }
input.addEventListener("input", grow);
$("#new").addEventListener("click", () => {
  if (busy) return;
  threadId = newId(); storage(s => s.setItem("threadId", threadId));
  Object.keys(runs).forEach(k => delete runs[k]); autoOpened.clear(); current = null;
  showEmpty(); showThread(); input.focus();
});

restore();
input.focus();
