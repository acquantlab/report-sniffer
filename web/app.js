import { Sniffer, hero } from "./sniffer.js";
import { THEMES, applyTheme, savedTheme, theme, themeId, rgba } from "./themes.js";
import { LANGS, NATIVE, REPORT, UI } from "./i18n.js";

applyTheme(savedTheme());

// ------------------------------------------------------------------ interface language
// chosen in the page (a cookie the server reads), else the operating system's language when the app has it, else English

const UI_LANG = LANGS.includes(document.documentElement.lang) ? document.documentElement.lang : "en";
// in the app's own window (not a browser tab): no Quit button (closing the window quits) and files are saved
// through the system's Save dialog
const IN_WINDOW = document.documentElement.dataset.native === "1";
const tr = (k, ...a) => { const v = UI[UI_LANG][k] ?? UI.en[k]; return typeof v === "function" ? v(...a) : v; };

function applyUI() {
  for (const el of document.querySelectorAll("[data-i18n]")) el.textContent = tr(el.dataset.i18n);
  for (const el of document.querySelectorAll("[data-i18n-html]")) el.innerHTML = tr(el.dataset.i18nHtml);
  for (const el of document.querySelectorAll("[data-i18n-ph]")) el.placeholder = tr(el.dataset.i18nPh);
  for (const el of document.querySelectorAll("[data-i18n-aria]")) el.setAttribute("aria-label", tr(el.dataset.i18nAria));
  const options = LANGS.map((c) => `<option value="${c}">${NATIVE[c]}</option>`).join("");
  for (const id of ["#opt-lang", "#lang2", "#opt-ui"]) document.querySelector(id).innerHTML = options;
  document.querySelector("#opt-lang").value = UI_LANG;          // the report follows the interface unless changed
  document.querySelector("#opt-ui").value = UI_LANG;
  document.documentElement.classList.add("ui-ready");
}
applyUI();

// the interface language: remembered for a year, read by the server (its messages follow it), then the page reloads
document.querySelector("#opt-ui").addEventListener("change", (e) => {
  document.cookie = `sniffer_ui=${encodeURIComponent(e.target.value)}; path=/; max-age=31536000; SameSite=Strict`;
  location.reload();
});

// colour themes: swatches on the home page and in the reading bar
function renderThemePick() {
  for (const box of document.querySelectorAll(".theme-pick")) {
    box.innerHTML = Object.entries(THEMES).map(([id, th]) =>
      `<button type="button" data-theme-id="${id}" title="${th.name[UI_LANG] || th.name.en}" aria-label="${th.name[UI_LANG] || th.name.en}" ` +
      `aria-pressed="${id === themeId()}" style="background:${th.swatch}"></button>`).join("");
  }
}
renderThemePick();
document.addEventListener("click", (e) => {
  const b = e.target.closest(".theme-pick button[data-theme-id]");
  if (!b) return;
  e.preventDefault();
  applyTheme(b.dataset.themeId);
  renderThemePick();
  state.director?.redraw();
});

// any unexpected error is shown on screen instead of leaving a still screen
function showError(msg) {
  let bar = document.getElementById("errbar");
  if (!bar) {
    bar = document.createElement("div");
    bar.id = "errbar";
    document.body.append(bar);
  }
  bar.textContent = tr("error", msg);
}
window.addEventListener("error", (e) => showError(e.message || String(e.error)));
window.addEventListener("unhandledrejection", (e) => showError(e.reason?.message || String(e.reason)));

const $ = (s) => document.querySelector(s);
// HTML-escapes text for markup and for attribute values in either kind of quote ('…' holds the JSON of search results)
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const reduced = matchMedia("(prefers-reduced-motion: reduce)").matches;

async function api(path, opts = {}) {
  const r = await fetch(path, opts);
  if (!r.ok) {
    let msg = r.statusText;
    try { msg = (await r.json()).detail || msg; } catch {}
    throw new Error(msg);
  }
  return r.json();
}
const postJSON = (path, body) => api(path, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });

function show(id) {
  for (const s of document.querySelectorAll(".screen")) s.hidden = s.id !== id;
}

// ------------------------------------------------------------------ home

const state = { status: null, analysis: null, director: null };

async function refreshStatus() {
  try { state.status = await api("/api/status"); } catch { state.status = null; }
  const st = $("#ai-state");
  st.textContent = state.status?.ai ? tr("ai_on", state.status.ai_name) : tr("ai_off");
  st.classList.toggle("off", !state.status?.ai);
}

// saves a file the server makes (report, slides, workbook, original document): in the app's window through the
// system's Save dialog, in a browser as a normal download
async function saveFile(url, fallbackName = "") {
  const bridge = window.pywebview?.api;
  if (IN_WINDOW && bridge?.save) {
    const r = await bridge.save(url);
    if (r?.error) throw new Error(r.error);
    if (r?.path) toast(tr("saved", r.path));
    return;
  }
  const res = await fetch(url);
  if (!res.ok) {
    let msg = res.statusText;
    try { msg = (await res.json()).detail || msg; } catch {}
    throw new Error(msg);
  }
  const cd = res.headers.get("content-disposition") || "";
  // filename* holds the real name (Greek, Japanese…); filename="…" its ASCII spelling
  const star = (cd.match(/filename\*=UTF-8''([^;]+)/i) || [])[1];
  let name = (cd.match(/filename="([^"]+)"/) || [])[1] || fallbackName || "document";
  try { if (star) name = decodeURIComponent(star); } catch { /* malformed: keep the ASCII name */ }
  const link = document.createElement("a");
  link.href = URL.createObjectURL(await res.blob());
  link.download = name;
  document.body.append(link); link.click(); link.remove();
  setTimeout(() => URL.revokeObjectURL(link.href), 20000);
}

function toast(msg) {
  let el = document.getElementById("toast");
  if (!el) { el = document.createElement("div"); el.id = "toast"; el.setAttribute("role", "status"); document.body.append(el); }
  el.textContent = msg; el.hidden = false;
  clearTimeout(toast.timer);
  toast.timer = setTimeout(() => { el.hidden = true; }, 5000);
}

let searchSeq = 0;
$("#search-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const q = $("#q").value.trim();
  if (!q) return;
  const seq = ++searchSeq;
  const box = $("#results");
  box.innerHTML = `<p class="empty">${esc(tr("searching", q))}</p>`;
  let res;
  try { res = await api("/api/search?q=" + encodeURIComponent(q)); } catch (err) {
    box.innerHTML = `<p class="error">${esc(err.message)}</p>`; return;
  }
  if (seq !== searchSeq) return;
  box.innerHTML = renderResults(res);
});

function renderResults(res) {
  const parts = [];
  if (res.sec.length) parts.push(group(tr("g_sec"), tr("g_sec_src"), res.sec.map((c) =>
    hit({ kind: "sec", query: c.ticker || String(c.cik) }, c.name, c.ticker || `CIK ${c.cik}`,
      c.ticker ? tr("read_filing") : `${tr("sec_noticker", c.form)} · ${tr("read_filing")}`))));
  if (res.esef.length) parts.push(group(tr("g_esef"), tr("g_esef_src"), res.esef.map((e) =>
    hit({ kind: "esef", query: e.lei }, e.name, e.country, tr("read_report")))));
  if (res.market.length) parts.push(group(tr("g_market"), tr("g_market_src"), res.market.map((m) =>
    hit({ kind: "market", symbol: m.symbol }, m.name, m.symbol, `${m.type_label}${m.exchange ? " · " + m.exchange : ""} · ${tr("read_filing")}`))));
  if (!parts.length) parts.push(`<p class="empty">${esc(tr("no_results"))}</p>`);
  for (const e of res.errors || []) parts.push(`<p class="note">${esc(e)}</p>`);
  return parts.join("");
}
function group(title, src, items) {
  return `<div class="group"><h3>${esc(title)} <span class="src">· ${esc(src)}</span></h3>${items.slice(0, 6).join("")}</div>`;
}
function hit(req, name, tk, what) {
  const q = new URLSearchParams({ kind: req.kind, query: req.query || "", symbol: req.symbol || "" });
  const more = req.kind === "market" ? "" :
    `<button class="more" type="button" aria-expanded="false" data-docs='${esc(JSON.stringify({ kind: req.kind, query: req.query }))}'>${esc(tr("more_docs"))}</button>`;
  return `<div class="hit-row"><button class="hit" type="button" data-req='${esc(JSON.stringify(req))}'><b>${esc(name)}</b><span class="tk">${esc(tk || "")}</span><span class="what">${esc(what)}</span></button>` +
    `<button class="orig" type="button" data-orig="/api/original?${esc(q.toString())}" title="${esc(tr(req.kind === "market" ? "orig_csv_title" : "orig_title"))}">${esc(tr(req.kind === "market" ? "orig_csv" : "orig"))}</button>${more}</div>` +
    (more ? `<div class="docs" hidden></div>` : "");
}

// the other documents of a company: annual and quarterly reports, results releases, prospectuses, earlier years
async function toggleDocs(btn) {
  const box = btn.closest(".hit-row").nextElementSibling;
  const open = box.hidden;
  box.hidden = !open; btn.setAttribute("aria-expanded", String(open));
  if (!open || box.dataset.loaded) return;
  const req = JSON.parse(btn.dataset.docs);
  box.innerHTML = `<p class="note">${esc(tr("docs_loading"))}</p>`;
  try {
    const res = await api(`/api/documents?kind=${encodeURIComponent(req.kind)}&query=${encodeURIComponent(req.query)}`);
    box.innerHTML = res.documents.map((d) => {
      const r = { kind: req.kind, query: req.query, url: d.url, form: d.form };
      const q = new URLSearchParams(r);
      const when = [d.period && tr("doc_period", d.period), d.filed && tr("doc_filed", d.filed), d.lang].filter(Boolean).join(" · ");
      return `<div class="doc-row"><button class="hit" type="button" data-req='${esc(JSON.stringify(r))}'><span class="form">${esc(d.form)}</span>` +
        `<b>${esc(d.what)}</b><span class="what">${esc(when)}</span></button>` +
        `<button class="orig" type="button" data-orig="/api/original?${esc(q.toString())}" title="${esc(tr("orig_title"))}">${esc(tr("orig"))}</button></div>`;
    }).join("") || `<p class="note">${esc(tr("no_docs"))}</p>`;
    box.dataset.loaded = "1";
  } catch (err) {
    box.innerHTML = `<p class="error">${esc(err.message)}</p>`;
  }
}

// download the original document (SEC filing, ESEF report, or prices as CSV) without leaving the page
async function downloadOriginal(btn) {
  const label = btn.textContent;
  btn.disabled = true; btn.textContent = tr("orig_busy");
  try {
    await saveFile(btn.dataset.orig);
  } catch (err) {
    alert(tr("orig_failed") + " " + err.message);
  } finally {
    btn.disabled = false; btn.textContent = label;
  }
}
document.addEventListener("click", (e) => {
  const o = e.target.closest(".orig[data-orig]");
  if (o) return downloadOriginal(o);
  const m = e.target.closest(".more[data-docs]");
  if (m) return toggleDocs(m);
  const b = e.target.closest(".hit[data-req]");
  if (b) start(JSON.parse(b.dataset.req));
  const r = e.target.closest(".hit[data-open]");
  if (r) openAnalysis(r.dataset.open);
});

$("#url-form").addEventListener("submit", (e) => {
  e.preventDefault();
  const url = $("#url").value.trim();
  if (url) start({ kind: "url", url });
});

const drop = $("#drop"), file = $("#file");
drop.addEventListener("click", () => file.click());
drop.addEventListener("keydown", (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); file.click(); } });
drop.addEventListener("dragover", (e) => { e.preventDefault(); drop.classList.add("over"); });
drop.addEventListener("dragleave", () => drop.classList.remove("over"));
drop.addEventListener("drop", (e) => { e.preventDefault(); drop.classList.remove("over"); if (e.dataTransfer.files[0]) upload(e.dataTransfer.files[0]); });
file.addEventListener("change", () => { if (file.files[0]) upload(file.files[0]); });

async function upload(f) {
  const fd = new FormData();
  fd.append("file", f);
  fd.append("lang", $("#opt-lang").value);
  show("loading"); loadingReset(tr("uploading", f.name));
  try { const { job } = await api("/api/upload", { method: "POST", body: fd }); await follow(job); } catch (err) { loadingError(err.message); }
}

async function start(req) {
  req.lang = $("#opt-lang").value;
  show("loading"); loadingReset(tr("preparing"));
  try { const { job } = await postJSON("/api/analyze", req); await follow(job); } catch (err) { loadingError(err.message); }
}

function loadingReset(step) {
  $("#load-step").textContent = step; $("#load-bar").style.width = "2%";
  $("#load-error").hidden = true; $("#load-back").hidden = true;
}
function loadingError(msg) {
  $("#load-error").textContent = msg; $("#load-error").hidden = false; $("#load-back").hidden = false;
  $("#load-step").textContent = tr("not_started");
}
$("#load-back").addEventListener("click", () => { show("home"); loadRecent(); });

async function follow(job) {
  for (;;) {
    const j = await api("/api/job/" + job);
    $("#load-step").textContent = j.step;
    $("#load-bar").style.width = Math.round(j.progress * 100) + "%";
    if (j.status === "done") return openAnalysis(j.analysis_id);
    if (j.status === "error") return loadingError(j.error);
    await sleep(250);
  }
}

async function loadRecent() {
  try {
    const list = await api("/api/recent");
    $("#recent").innerHTML = list.length ? `<h3>${esc(tr("recent"))}</h3>` + list.map((a) =>
      `<button class="hit" type="button" data-open="${esc(a.id)}"><b>${esc(a.title)}</b><span class="what">${esc(a.subtitle)}</span></button>`).join("") : "";
  } catch { /* server not ready */ }
}

// settings: the AI (optional, for the context of an analysis) and the SEC identity
const SUB_HELP = { claude_code: "sub_claude", codex: "sub_codex" };
const SUB_CMD = { claude_code: "claude", codex: "codex" };
function providerInfo(id) {
  return (state.status?.ai_providers?.providers || []).find((p) => p.id === id);
}
function showMode(mode) {
  for (const r of document.querySelectorAll("input[name=aimode]")) r.checked = r.value === mode;
  $("#mode-sub").hidden = mode !== "sub"; $("#mode-key").hidden = mode !== "key";
  showProvider(mode === "sub" ? $("#set-sub").value : $("#set-provider").value);
}
function showProvider(id) {
  const p = providerInfo(id);
  if (!p) return;
  $("#set-model").value = p.model || "";
  $("#set-model").placeholder = p.default_model || tr("model_default");
  if (p.cli) {
    $("#sub-state").innerHTML = `${esc(tr(SUB_HELP[id]))}<br><b>${esc(tr(p.installed ? "sub_found" : "sub_missing"))}</b> <code>${esc(SUB_CMD[id])}</code>`;
    return;
  }
  $("#set-key").value = "";
  $("#set-key").placeholder = p.has_key ? "••••••••" : { anthropic: "sk-ant-…", openai: "sk-…", openrouter: "sk-or-…", gemini: "AIza…" }[id] || "";
  $("#key-state").textContent = p.has_key ? tr("key_saved") : tr("key_info");
}
async function openSettings() {
  await refreshStatus();
  const dlg = $("#settings");
  $("#set-ua").value = state.status?.sec_ua_custom ? state.status.sec_user_agent : "";
  const prov = state.status?.ai_providers?.providers || [];
  const opt = (p) => `<option value="${esc(p.id)}">${esc(p.name)}${p.has_key || p.installed ? " ✓" : ""}</option>`;
  $("#set-sub").innerHTML = prov.filter((p) => p.cli).map(opt).join("");
  $("#set-provider").innerHTML = prov.filter((p) => !p.cli).map(opt).join("");
  const act = state.status?.ai_providers?.active;
  if (act && providerInfo(act)?.cli) $("#set-sub").value = act;
  else if (act) $("#set-provider").value = act;
  $("#set-msg").hidden = true; $("#set-ok").hidden = true;
  showMode(act && !providerInfo(act)?.cli ? "key" : "sub");
  if (!dlg.open) dlg.showModal();
}
$("#open-settings").addEventListener("click", () => openSettings());
// in a browser tab the app has no window to close: it stops from here
$("#quit").addEventListener("click", async () => {
  state.director?.stop();
  try { await postJSON("/api/quit", {}); } catch { /* already stopped */ }
  const bye = document.createElement("p");
  bye.className = "bye"; bye.textContent = tr("stopped");
  document.body.replaceChildren(bye);
});
$("#ai-state").addEventListener("click", () => openSettings());
for (const r of document.querySelectorAll("input[name=aimode]")) r.addEventListener("change", () => showMode(r.value));
$("#set-sub").addEventListener("change", () => showProvider($("#set-sub").value));
$("#set-provider").addEventListener("change", () => showProvider($("#set-provider").value));
$("#set-save").addEventListener("click", async () => {
  const sub = document.querySelector("input[name=aimode]:checked")?.value !== "key";
  const pid = sub ? $("#set-sub").value : $("#set-provider").value;
  const body = { sec_user_agent: $("#set-ua").value.trim(), ai_provider: pid, ai_model: $("#set-model").value.trim() };
  if (!sub) {
    const k = $("#set-key").value.trim();
    if (k.toLowerCase() === tr("remove_word") || k.toLowerCase() === "remove") body.ai_remove = true;
    else if (k) body.ai_key = k;
  }
  const btn = $("#set-save"), msg = $("#set-msg"), ok = $("#set-ok");
  msg.hidden = true; ok.hidden = false; ok.textContent = tr("testing"); btn.disabled = true;
  try {
    await postJSON("/api/settings", body);
    const r = await postJSON("/api/ai/test", {});
    await refreshStatus();
    ok.textContent = tr("connected", r.provider);
    await sleep(900);
    $("#settings").close();
    if (state.ctxPending) { state.ctxPending = false; openContext(); }
  } catch (err) {
    ok.hidden = true; msg.textContent = err.message; msg.hidden = false;
    await refreshStatus();
  } finally { btn.disabled = false; }
});

// ------------------------------------------------------------------ reader

const iframe = $("#doc"), stage = $("#stage"), layer = $("#doc-layer");
const marksCv = $("#marks"), liveCv = $("#sniffer");

// report wording in the language of the analysis (web/i18n.js)
const L = () => REPORT[state.analysis?.lang] || REPORT.en;

// pacing: base seconds per stop, compressed for long documents, never by skipping figures
const BASE = { fig: 0.28, key: 0.7, head: 0.45, walk: 0.034, minHop: 0.12, maxHop: 1.4 };
const targetSeconds = (n) => Math.max(7, Math.min(36, 5 + n * 0.055));
const KEY_DWELL = 0.45;   // a headline figure stays selected long enough to read, however fast the pace
const HEADLINE = new Set(["revenue", "net_income", "eps_diluted", "cfo"]);
const headline = (s) => s.type === "f" && s.fact.key && s.fact.role === "cur" && HEADLINE.has(s.fact.metric);
const smooth = (u) => u * u * (3 - 2 * u);
const easeOut = (u) => 1 - (1 - u) ** 3;

$("#back").addEventListener("click", () => { state.director?.stop(); show("home"); loadRecent(); });
$("#play").addEventListener("click", () => state.director?.toggle());
$("#restart").addEventListener("click", () => state.director?.restart());
$("#download").addEventListener("click", (e) => { e.stopPropagation(); dlMenu(!!$("#dl-menu").hidden); });
$("#dl-menu").addEventListener("click", (e) => {
  const b = e.target.closest("[data-fmt]");
  if (b && state.analysis) downloadReport(state.analysis, b.dataset.fmt);
  dlMenu(false);
});
document.addEventListener("click", () => dlMenu(false));
document.addEventListener("keydown", (e) => { if (e.key === "Escape") dlMenu(false); });
function dlMenu(open) {
  $("#dl-menu").hidden = !open;
  $("#download").setAttribute("aria-expanded", String(open));
}
// ------------------------------------------------------------------ AI context (optional)
// The figures are read by rules; on request an AI puts them in context with the user's notes and, when it can
// search the web, the latest news. It runs while the reading goes on; the side panel shows the result.

async function openContext() {
  await refreshStatus();
  const on = !!state.status?.ai, web = !!state.status?.ai_web;
  $("#ctx-noai").hidden = on; $("#ctx-form").hidden = !on;
  $("#ctx-run").hidden = !on; $("#ctx-settings").hidden = on;
  $("#ctx-web").checked = web; $("#ctx-web").disabled = !web;
  $("#ctx-noweb").hidden = web;
  $("#ctx-notes").value = state.analysis?.reading?.notes ?? $("#ctx-notes").value;
  if (!$("#ctx").open) $("#ctx").showModal();
}
$("#ctx-open").addEventListener("click", openContext);
$("#ctx-settings").addEventListener("click", () => { $("#ctx").close(); state.ctxPending = true; openSettings(); });
$("#ctx-run").addEventListener("click", async () => {
  const a = state.analysis;
  if (!a) return;
  $("#ctx").close();
  const status = $("#r-ctx-status"), btn = $("#ctx-open");
  status.classList.remove("error"); status.textContent = tr("ctx_wait"); status.hidden = false; btn.disabled = true;
  $("#report").scrollTop = 0;
  try {
    const { job } = await postJSON("/api/context", { id: a.id, notes: $("#ctx-notes").value.trim(), web: $("#ctx-web").checked });
    for (;;) {
      const j = await api("/api/job/" + job);
      status.textContent = j.step;
      if (j.status === "error") throw new Error(j.error);
      if (j.status === "done") break;
      await sleep(600);
    }
    const fresh = await api("/api/doc/" + a.id);
    if (state.analysis?.id !== a.id) return;              // another document was opened meanwhile
    Object.assign(a, { reading: fresh.reading, ai: fresh.ai, ai_provider: fresh.ai_provider });
    status.hidden = true;
    showReading(a);
    if (state.director?.done) {                           // the card is already up: its footer names the AI now
      $("#finale").innerHTML = cardHTML(a, state.director.count);
      $("#finale .card")?.classList.add("in");
    }
  } catch (err) {
    status.textContent = err.message; status.classList.add("error");
  } finally { btn.disabled = false; }
});

$("#lang2").addEventListener("change", async () => {
  const a = state.analysis, lang = $("#lang2").value;
  $("#opt-lang").value = lang;
  if (!a || a.lang === lang) return;
  state.director?.stop();
  show("loading"); loadingReset(tr("relang", NATIVE[lang] || lang));
  try { const { job } = await postJSON("/api/relang", { id: a.id, lang }); await follow(job); } catch (err) { loadingError(err.message); }
});

async function openAnalysis(id) {
  const a = await api("/api/doc/" + id);
  state.analysis = a;
  show("reader");
  const T = L();
  $("#lang2").value = a.lang || "it";
  $("#r-title").textContent = a.title;
  $("#r-sub").textContent = a.subtitle;
  $("#r-counter").innerHTML = T.counter('<b id="r-n">0</b>', `<span id="r-m">${Object.keys(a.facts).length.toLocaleString(T.locale)}</span>`);
  $("#r-other-title").textContent = T.other;
  const shown = a.pages.map((p) => p.n);
  $("#r-pages").textContent = a.total_pages > shown.length ? T.pages_some(shown.map(pageLabel).join(", "), a.total_pages) : T.pages_all(a.total_pages);
  $("#r-warn").textContent = (a.warnings || []).join(" ");
  $("#r-reading").hidden = true; $("#r-reading").innerHTML = "";
  $("#r-ctx-status").hidden = true; $("#ctx-notes").value = "";
  if (a.reading) showReading(a);                     // context asked for earlier
  state.director?.stop();
  await new Promise((res) => { iframe.onload = res; iframe.src = `/api/doc/${id}/view`; });
  state.director = new Director(a);
  state.director.restart();
}

// page numbers as printed in the document ("F-7", "22") when known, else the page's position
function pageLabel(n) {
  return state.analysis?.page_labels?.[n] || state.analysis?.page_labels?.[String(n)] || n;
}

function fmtPages(pages) {
  if (!pages?.length) return "";
  const T = L();
  return esc(T.pg(pages.map(pageLabel).join(", "), pages.length > 1));      // goes into innerHTML
}

class Director {
  constructor(a) {
    this.a = a;
    this.doc = iframe.contentDocument;
    this.raf = 0;
    this.playing = false;
    this.measure();
    this.sniffer = new Sniffer(this.U);
    new ResizeObserver(() => this.relayout()).observe(stage);
  }

  measure() {
    const d = this.doc, root = d.documentElement;
    const main = d.getElementById("sa-doc");
    this.docW = Math.max(main.scrollWidth, root.scrollWidth);
    iframe.style.width = this.docW + "px";
    this.docH = root.scrollHeight;
    iframe.style.height = this.docH + "px";
    this.docH = root.scrollHeight;
    iframe.style.height = this.docH + "px";
    this.textScale();
    this.buildStops();
  }

  // the size of the document's text (the median line height) sets the scale of the sniffer and of the marks
  textScale() {
    const d = this.doc, root = d.getElementById("sa-doc");
    const walker = d.createTreeWalker(root, NodeFilter.SHOW_TEXT, {
      acceptNode: (n) => n.parentElement && n.parentElement.closest("style,script,.sa-pnum") ? NodeFilter.FILTER_REJECT : NodeFilter.FILTER_ACCEPT,
    });
    const range = d.createRange(), hs = [];
    let node;
    while ((node = walker.nextNode()) && hs.length < 4000) {
      if (!node.data.trim()) continue;
      range.selectNodeContents(node);
      const r = range.getClientRects()[0];
      if (r && r.width >= 1 && r.height >= 1) hs.push(r.height);
    }
    hs.sort((p, q) => p - q);
    this.U = Math.max(0.45, Math.min(2.2, (hs.length ? hs[hs.length >> 1] : 16) / 16));
  }

  relayout() {
    const W = stage.clientWidth, H = stage.clientHeight, dpr = devicePixelRatio || 1;
    for (const cv of [marksCv, liveCv]) { cv.width = Math.round(W * dpr); cv.height = Math.round(H * dpr); }
    const pageW = Math.max(...[...this.doc.querySelectorAll(".sa-page")].map((p) => p.getBoundingClientRect().width), 600);
    this.scale = Math.min(1.15, (W - 24) / pageW);
    this.W = W; this.H = H; this.dpr = dpr;
    if (!this.playing && this.timeline) this.frame(performance.now(), true);
  }

  rectOf(el) {
    const r = el.getBoundingClientRect();
    return { x: r.left, y: r.top, w: r.width, h: r.height };
  }

  buildStops() {
    const a = this.a, stops = [];
    this.lanes = {};
    for (const sec of this.doc.querySelectorAll(".sa-page")) {
      const n = +sec.dataset.page;
      const pr = this.rectOf(sec);
      this.lanes[n] = pr.x + pr.w / 2;
      const items = [];
      for (const el of sec.querySelectorAll("[data-h]")) {
        const range = this.doc.createRange();
        range.selectNodeContents(el);
        const rr = range.getBoundingClientRect(), r = { x: rr.left, y: rr.top, w: rr.width, h: rr.height };
        if (r.w > 2 && r.h > 2) items.push({ type: "h", el, r, text: el.textContent.trim(), page: n });
      }
      for (const el of sec.querySelectorAll("[data-f]")) {
        const f = a.facts[el.dataset.f];
        if (!f) continue;
        const r = this.rectOf(el);
        if (r.w < 2 || r.h < 2) continue;
        items.push({ type: "f", el, r, id: el.dataset.f, fact: f, page: n, label: this.rowLabelRect(el) });
      }
      // reading order: rows top to bottom, left to right within a row
      items.sort((p, q) => (Math.abs(p.r.y - q.r.y) < 6 ? p.r.x - q.r.x : p.r.y - q.r.y));
      if (!items.length) items.push({ type: "page", r: this.rectOf(sec), page: n });
      items[0].first = true;
      stops.push(...items);
    }
    this.allStops = stops;
  }

  rowLabelRect(el) {
    const tr = el.closest("tr");
    if (!tr) return null;
    for (const td of tr.children) {
      if (td.contains(el)) break;
      const t = td.textContent.trim();
      if ((t.match(/\p{L}/gu) || []).length >= 3) {
        const range = this.doc.createRange();
        range.selectNodeContents(td);
        const rr = range.getBoundingClientRect();
        return { x: rr.left, y: rr.top, w: rr.width, h: rr.height, text: t };
      }
    }
    return null;
  }

  // every figure is visited; the pace adapts to how many there are
  plan() {
    const stops = this.allStops;
    const pts = stops.map((s) => this.anchor(s));
    const dwell = (s) => s.type === "h" || s.type === "page" ? BASE.head : s.fact.key ? BASE.key : BASE.fig;
    this.start0 = { x: pts[0].x - 40 * this.U, y: pts[0].y - 120 * this.U };
    let prev = this.start0;
    const hops = stops.map((s, i) => {
      const d = Math.hypot(pts[i].x - prev.x, pts[i].y - prev.y);
      prev = pts[i];
      return [Math.min(BASE.maxHop, Math.max(BASE.minHop, BASE.walk * Math.sqrt(d))), dwell(s)];
    });
    const natural = hops.reduce((t, [p, q]) => t + p + q, 0);
    const figures = stops.filter((s) => s.type === "f").length;
    const k = Math.max(0.03, Math.min(1, targetSeconds(figures) / natural));
    let t = 0;
    this.timeline = stops.map((s, i) => {
      const stay = headline(s) ? Math.max(KEY_DWELL, hops[i][1] * k) : hops[i][1] * k;
      const seg = { s, p: pts[i], t0: t, t1: t + hops[i][0] * k, t2: t + hops[i][0] * k + stay };
      t = seg.t2;
      return seg;
    });
    this.planned = new Set(stops.filter((x) => x.type === "f").map((x) => String(x.id)));
    this.total = t;
    const mul = Math.min(5, 1 / Math.sqrt(k));
    this.pace = { k, mul, cam: Math.min(14, 4 * mul), obs: Math.max(380, 900 / mul) };
    this.sniffer.speed = mul;
  }

  // the nose stops at the left edge of what it reads, on its line; the roll lies to the left of it
  anchor(s) {
    if (s.type === "page") return { x: s.r.x + 90 * this.U, y: s.r.y + 60 * this.U };
    return { x: s.r.x - 4 * this.U, y: s.r.y + s.r.h / 2 };
  }

  restart() {
    this.stop();
    $("#finale").hidden = true; $("#finale").innerHTML = "";
    this.relayout();
    this.plan();
    this.clock = 0; this.idx = -1; this.marks = []; this.cur = null; this.labelled = new Set(); this.listed = new Set();
    this.done = false;
    this.count = 0; this.page = null;
    $("#r-n").textContent = "0";
    $("#r-other-list").innerHTML = "";
    $("#r-sec-title").textContent = "";
    $("#r-table thead").innerHTML = ""; $("#r-table tbody").innerHTML = "";
    this.cam = { x: 0, y: Math.max(0, this.start0.y - 200) };
    this.sniffer.place(this.start0.x, this.start0.y);
    this.playing = true;
    $("#play").textContent = tr("pause");
    this.last = performance.now();
    this.raf = requestAnimationFrame((t) => this.frame(t));
  }

  // a new theme while paused: draw once more with its colours
  redraw() {
    if (!this.playing && this.timeline) this.frame(performance.now(), true);
  }

  stop() {
    cancelAnimationFrame(this.raf);
    this.playing = false;
    $("#play").textContent = tr("play");
  }

  toggle() {
    if (this.done) return this.restart();
    if (this.playing) return this.stop();
    this.playing = true; $("#play").textContent = tr("pause");
    this.last = performance.now();
    this.raf = requestAnimationFrame((t) => this.frame(t));
  }

  bodyAt(t) {
    const tl = this.timeline;
    let prev = this.start0;
    for (let i = 0; i < tl.length; i++) {
      const g = tl[i];
      if (t < g.t0) return prev;
      if (t < g.t1) {
        const e = smooth((t - g.t0) / (g.t1 - g.t0));
        return { x: prev.x + (g.p.x - prev.x) * e, y: prev.y + (g.p.y - prev.y) * e };
      }
      if (t < g.t2) return g.p;
      prev = g.p;
    }
    return prev;
  }

  frame(now, still = false) {
    const dt = still ? 0 : Math.min(0.05, (now - this.last) / 1000);
    this.last = now;
    if (!still) this.clock += dt;
    const t = this.clock;

    while (this.timeline && this.idx + 1 < this.timeline.length && t >= this.timeline[this.idx + 1].t1) {
      this.idx++;
      this.arrive(this.timeline[this.idx]);
    }
    const goal = this.bodyAt(t);
    if (!still) this.sniffer.update(goal, dt);

    // the camera follows the sniffer down the page, and stays on the middle of the page sideways
    const s = this.scale, vw = this.W / s, vh = this.H / s;
    const tx = Math.max(0, Math.min(this.docW - vw, (this.lanes[this.page] ?? this.sniffer.x) - vw * 0.5));
    const ty = Math.max(0, Math.min(this.docH - vh, this.sniffer.y - vh * 0.42));
    const k = still || reduced ? 1 : Math.min(1, dt * this.pace.cam);
    this.cam.x += (Math.max(0, tx) - this.cam.x) * k;
    this.cam.y += (ty - this.cam.y) * k;
    if (this.docW * s <= this.W) this.cam.x = -(this.W / s - this.docW) / 2;
    layer.style.transform = `scale(${s}) translate(${-this.cam.x}px, ${-this.cam.y}px)`;

    this.draw();

    if (!this.done && this.timeline && t > this.total + 0.6) {
      this.done = true;
      if (this.cur) { this.cur.t1 = t; this.cur = null; }
      this.finale();
    }
    if (this.playing) this.raf = requestAnimationFrame((tt) => this.frame(tt));
  }

  // a stop is reached: the figure (or heading) becomes the live selection and the previous one settles;
  // the nose of the sniffer lights up (the figure is read where it is printed, nothing is written next to the roll)
  arrive(g) {
    const s = g.s, now = this.clock;
    if (s.first && s.page !== this.page) this.enterPage(s.page);
    if (this.cur) this.cur.t1 = now;
    this.cur = null;
    if (s.type === "page") return;
    const text = (s.type === "f" ? s.el.textContent : s.text || "").trim();
    this.cur = { kind: s.type === "h" ? "head" : "found", r: s.r, t: now, key: s.type === "f" && s.fact.key, n: Math.max(1, Math.min(24, text.length)) };
    this.marks.push(this.cur);
    if (s.type !== "f") return;
    const lk = s.label && `${Math.round(s.label.x)}|${Math.round(s.label.y)}`;
    if (lk && !this.labelled.has(lk)) { this.labelled.add(lk); this.marks.push({ kind: "label", r: s.label, t: now }); }
    this.sniffer.sniff();
    this.count++;
    $("#r-n").textContent = this.count.toLocaleString(L().locale);
    this.report(s);
  }

  enterPage(n) {
    this.page = n;
    const a = this.a, p = a.pages.find((x) => x.n === n), T = L();
    $("#r-sec-title").textContent = `${p ? p.title : T.page + " " + pageLabel(n)} · ${T.pg(pageLabel(n))}`;
    const cols = a.cols[n] || [T.value];
    const rows = (a.rows[n] || []).filter((r) => r.cells.some((fid) => fid !== null && this.planned.has(String(fid))));
    // a page without statement lines has no table: its figures go to "Other figures read"
    $("#r-table thead").innerHTML = rows.length ? `<tr><th></th>${cols.map((c) => `<th>${esc(c)}</th>`).join("")}</tr>` : "";
    this.rowOf = new Map();
    $("#r-table tbody").innerHTML = rows.map((r, i) => {
      r.cells.forEach((fid, j) => fid !== null && this.rowOf.set(String(fid), [i, j]));
      return `<tr data-i="${i}"><td>${esc(r.label)}</td>${r.cells.map(() => `<td class="wait">·</td>`).join("")}</tr>`;
    }).join("");
  }

  report(s) {
    const pos = this.rowOf?.get(String(s.id));
    if (pos) {
      const tr = $(`#r-table tbody tr[data-i="${pos[0]}"]`);
      const td = tr.children[pos[1] + 1];
      td.textContent = s.fact.value_fmt; td.classList.remove("wait");
      for (const h of document.querySelectorAll("#r-table tr.hot")) h.classList.remove("hot");
      tr.classList.add("hot");
      tr.scrollIntoView({ block: "nearest" });
      return;
    }
    // the same line is often printed in the summary, the MD&A and the statements: list it once
    const k = `${s.fact.label}|${s.fact.period || ""}|${s.fact.value_fmt}`;
    if (this.listed.has(k)) return;
    this.listed.add(k);
    const li = document.createElement("li");
    li.innerHTML = `<span>${esc(s.fact.label)}${s.fact.period ? `<small>${esc(s.fact.period)}</small>` : ""}</span><b>${esc(s.fact.value_fmt)}</b><i>${esc(L().pg(pageLabel(s.page)))}</i>`;
    const list = $("#r-other-list");
    list.prepend(li);
    while (list.children.length > 400) list.lastChild.remove();
  }

  // Marks, like a selection in a terminal: the highlight steps over the figure one character cell at a time behind a caret,
  // stays while the figure is read, then settles into a lighter highlight with an underline that stays: every figure
  // read remains clearly marked on the original page. No boxes.
  draw() {
    const s = this.scale, dpr = this.dpr, now = this.clock, th = theme(), U = this.U;
    const set = (ctx) => { ctx.setTransform(dpr * s, 0, 0, dpr * s, -this.cam.x * s * dpr, -this.cam.y * s * dpr); };
    const sweep = Math.max(0.1, 0.32 / (this.pace?.mul || 1)), settle = 0.55;
    const top = this.cam.y - 60, bottom = this.cam.y + this.H / s + 60;
    const grown = (mk) => {
      if (reduced) return 1;
      const g = easeOut(Math.min(1, (now - mk.t) / sweep));
      return mk.n ? Math.ceil(g * mk.n) / mk.n : g;
    };

    // on the page (multiplied, so the print stays black)
    const m = marksCv.getContext("2d");
    m.setTransform(1, 0, 0, 1, 0, 0);
    m.clearRect(0, 0, marksCv.width, marksCv.height);
    set(m);
    for (const mk of this.marks) {
      const r = mk.r;
      if (r.y > bottom || r.y + r.h < top) continue;
      const w = (r.w + 4) * grown(mk), x = r.x - 2;
      if (mk.kind === "label") {
        const rest = smooth(Math.max(0, Math.min(1, (now - mk.t - sweep) / 0.9)));
        m.fillStyle = rgba(th.marker, 0.5 - 0.3 * rest);
        m.fillRect(x, r.y, w, r.h);
        continue;
      }
      const rest = mk === this.cur ? 0 : smooth(Math.min(1, (now - (mk.t1 ?? mk.t)) / settle));
      const color = mk.kind === "head" ? th.sight : th.ping, quiet = mk.kind === "head" ? 0.08 : mk.key ? 0.34 : 0.24;
      m.fillStyle = rgba(color, 0.42 + (quiet - 0.42) * rest);
      m.fillRect(x, r.y, w, r.h);
      m.fillStyle = color;
      m.fillRect(x, r.y + r.h + 0.5 * U, w, Math.max(1, (mk.key ? 2.2 : 1.5) * U));
    }

    // above the page: the caret of the live selection and the sniffer
    const c = liveCv.getContext("2d");
    c.setTransform(1, 0, 0, 1, 0, 0);
    c.clearRect(0, 0, liveCv.width, liveCv.height);
    set(c);
    const cur = this.cur;
    if (cur && !reduced) {
      const g = grown(cur);
      if (g < 1 || Math.floor(performance.now() / 380) % 2 === 0) {
        c.fillStyle = cur.kind === "head" ? th.sight : th.ping;
        c.fillRect(cur.r.x - 2 + (cur.r.w + 4) * g, cur.r.y - 1, Math.max(1.2, 1.6 * U), cur.r.h + 2);
      }
    }
    this.sniffer.draw(c);
  }

  async finale() {
    const a = this.a, box = $("#finale"), T = L();
    box.hidden = false;
    const finds = a.findings || [];
    const per = reduced ? 300 : this.pace.obs;
    if (a.reading) {
      showReading(a);
      if (a.reading.summary) {
        box.innerHTML = `<div class="obs sum"><h2>${esc(T.summary)}</h2><p>${esc(a.reading.summary)}</p></div>`;
        await sleep(30); box.querySelector(".sum").classList.add("in");
        await sleep(Math.max(1400, per * 2.2));
      }
    }
    if (finds.length) {
      box.innerHTML = `<div class="obs"><h2>${esc(T.obs)}</h2><ol>${finds.map((f) =>
        `<li>${esc(f.text)} <span class="pg">${fmtPages(f.pages)}</span></li>`).join("")}</ol></div>`;
      for (const li of box.querySelectorAll("li")) { await sleep(60); li.classList.add("in"); await sleep(per); }
      await sleep(per * 0.6);
    }
    box.innerHTML = cardHTML(a, this.count);
    await sleep(40);
    box.querySelector(".card").classList.add("in");
    this.stop();
    $("#play").textContent = tr("replay");
  }
}

// the AI context, in the side panel: kind of document, summary, key points by theme, the news with its links
function showReading(a) {
  const r = a.reading, T = L(), el = $("#r-reading");
  const news = r.news || [];
  const cite = (ids) => (ids || []).filter((i) => news[i]).map((i) => `<sup><a href="#ctx-n${i}">[${i + 1}]</a></sup>`).join("");
  el.innerHTML = `<h3>${esc(T.understood)}${r.doc_type ? ` · <span>${esc(r.doc_type)}</span>` : ""}</h3>` +
    (r.notes ? `<p class="notes"><b>${esc(T.notes)}:</b> ${esc(r.notes)}</p>` : "") +
    (r.summary ? `<p class="sum">${esc(r.summary)}</p>` : "") +
    (r.sections || []).map((s) => `<h4>${esc(s.title)}</h4><ul>${s.points.map((p) =>
      `<li>${esc(p.text)} <span class="pg">${fmtPages(p.pages)}</span>${cite(p.news)}</li>`).join("")}</ul>`).join("") +
    (news.length ? `<h4>${esc(T.news)}</h4><ol class="news">${news.map((n, i) =>
      `<li id="ctx-n${i}"><a href="${esc(n.url)}" target="_blank" rel="noopener noreferrer">${esc(n.title)}</a>` +
      ` <span class="src">${esc([n.source, n.date].filter(Boolean).join(" · "))}</span>` +
      (n.summary ? `<br>${esc(n.summary)}` : "") + `</li>`).join("")}</ol>` : "") +
    (r.web === false ? `<p class="pg">${esc(T.no_news)}</p>` : "");
  el.hidden = false;
  $("#report").scrollTop = 0;
}

function cardHTML(a, count) {
  const T = L(), lang = a.lang || "en";
  const passed = (a.checks || []).filter((c) => c.ok).length;
  const tiles = (a.card || []).map((t) => {
    const y = t.yoy_display ? `<div class="y ${t.yoy_display.startsWith("+") ? "up" : "down"}">${esc(t.yoy_display)} <span class="vs">${esc(t.vs ? T.vs(t.vs) : T.yoy)}</span></div>`
      : t.prev_display ? `<div class="was">${esc(T.was(t.prev_display))}${t.vs ? ` (${esc(t.vs)})` : ""}</div>` : "";
    // the label in the report language (analyses read by older versions carry only Italian and English)
    const label = t.label || (lang === "en" && t.en ? t.en : t.it);
    return `<div class="tile"><div class="l">${esc(label)}</div><div class="v">${esc(t.display)}</div>` +
      (t.exact ? `<div class="x">${esc(t.exact)}</div>` : "") + y + (t.note ? `<div class="nt">${esc(t.note)}</div>` : "") +
      `<span class="pg">${fmtPages(t.pages)}</span></div>`;
  }).join("");
  const nchk = (a.checks || []).length;
  // the wording is ours (no markup in it); the numbers are wrapped in <b>
  const counts = T.read(`<b>${count.toLocaleString(T.locale)}</b>`) + " · " + (nchk ? T.checks(`<b>${passed}</b>`, nchk) : esc(T.no_checks));
  return `<div class="card"><h2>${esc(a.title)}</h2><p class="sub">${esc(a.subtitle)}</p>
    <div class="tiles">${tiles}</div>
    <ul>${(a.card_findings || []).map((f) => `<li>${esc(f.text)} <span class="pg">${fmtPages(f.pages)}</span></li>`).join("")}</ul>
    <div class="foot"><span>${counts}</span>
    <span>${esc(T.foot_det)}${a.ai ? " · " + esc(T.foot_ai(a.ai_provider || "AI")) : ""}</span></div></div>`;
}

// ------------------------------------------------------------------ updates
// a new release on GitHub: the downloadable app installs it and restarts; a copy run from the source (or one
// that cannot write where it is installed) links to the release page

async function checkUpdate() {
  let u;
  try { u = await api("/api/update"); } catch { return; }
  if (!u.newer) return;
  const box = $("#update");
  const notes = `<a href="${esc(u.url)}" target="_blank" rel="noopener noreferrer">${esc(tr("upd_notes"))}</a>`;
  box.innerHTML = `<span class="msg">${tr("upd_avail", `<b>${esc(u.latest)}</b>`, esc(u.current))} ` +
    (u.can_install ? "" : esc(tr("upd_manual"))) + `</span>` + notes +
    (u.can_install ? `<button type="button" id="upd-now">${esc(tr("upd_now"))}</button>`
      : `<a class="key" href="${esc(u.url)}" target="_blank" rel="noopener noreferrer">${esc(tr("upd_get"))}</a>`);
  box.hidden = false;
  $("#upd-now")?.addEventListener("click", installUpdate);
}

async function installUpdate() {
  const box = $("#update");
  box.innerHTML = `<span class="msg" id="upd-step">${esc(tr("preparing"))}</span><span class="bar"><i id="upd-bar"></i></span>`;
  try {
    const { job } = await postJSON("/api/update", {});
    for (;;) {
      const j = await api("/api/job/" + job);
      $("#upd-step").textContent = j.step;
      $("#upd-bar").style.width = Math.round(j.progress * 100) + "%";
      if (j.status === "error") throw new Error(j.error);
      if (j.status === "done") break;
      await sleep(500);
    }
    $("#upd-step").textContent = tr("upd_restart");          // the app quits; the new version starts by itself
  } catch (err) {
    $("#upd-step").textContent = tr("upd_failed") + " " + err.message;
    $("#upd-step").classList.add("error");
  }
}

// ------------------------------------------------------------------ downloadable report

// the server-made file (PDF report, PowerPoint deck, Excel figures)
function downloadReport(a, fmt = "report.pdf") {
  saveFile(`/api/doc/${a.id}/${fmt}?theme=${encodeURIComponent(themeId())}`).catch((err) => alert(tr("orig_failed") + " " + err.message));
}

const deep = new URLSearchParams(location.search).get("doc");

// in a browser tab the reader is tested with Chromium; other browsers get a notice (the app's own window is fine)
const isChromium = !!navigator.userAgentData || /\b(Chrome|Chromium|Edg|OPR|Brave)\//.test(navigator.userAgent);
if (!isChromium && !IN_WINDOW) $("#browser-warn").hidden = false;
if (IN_WINDOW) $("#quit").hidden = true;                // closing the window quits

refreshStatus().then(() => { if (state.status?.version) $("#version").textContent = "v" + state.status.version; });
checkUpdate();
loadRecent();
hero($("#hero"), reduced);
if (deep) openAnalysis(deep);
