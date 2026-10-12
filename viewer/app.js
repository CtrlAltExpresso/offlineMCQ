"use strict";
/* LiveMCQ — offline archive viewer.
   Reads prebuilt shards in ./data and the raw per-exam maps in ../api_data.
   Everything here runs from local files; no network required. */

const BASE = "../api_data";    // relative to /viewer/

const view = document.getElementById("view");
const backBtn = document.getElementById("backBtn");
const topbarCount = document.getElementById("topbarCount");
const pdfModal = document.getElementById("pdfModal");
const pdfFrame = document.getElementById("pdfModalFrame");
const pdfModalTitle = document.getElementById("pdfModalTitle");
const toast = document.getElementById("toast");

let MEDIA_URL = {};   // url -> rel_path (relative to the media root)
let MEDIA_BASE = "../media/";   // resolved once at boot: desktop <-> android bundle
let STREAMS = {};     // video id -> {base, renditions:[{rendition,url,size,...}]}

/* The media tree is laid out differently per deployment:
     desktop  ->  <repo>/media/<host>/<path>      => "../media/" + rel
     android  ->  <bundle>/<host>/<path>          => "../" + rel
   Probe candidate bases once at boot and keep the first that actually serves
   a real file, so images / thumbnails / PDFs stop 404-ing. */
const mediaURL = (rel) => MEDIA_BASE + rel;
async function probeMediaBase() {
  const rels = Object.values(MEDIA_URL).filter(Boolean);
  if (!rels.length) return;
  const sample = rels.filter(r => /\.(jpe?g|png|webp|gif)$/i.test(r)).slice(0, 4);
  if (!sample.length) sample.push(...rels.slice(0, 4));
  for (const base of ["../media/", "../", "./media/", "media/"]) {
    for (const rel of sample) {
      let ok = false;
      try {
        const r = await fetch(base + rel, { method: "HEAD", cache: "no-store" });
        ok = r.ok || r.status === 206;
      } catch (e) {
        try {
          const r2 = await fetch(base + rel, { headers: { Range: "bytes=0-0" }, cache: "no-store" });
          ok = r2.ok || r2.status === 206;
        } catch (e2) { ok = false; }
      }
      if (ok) { MEDIA_BASE = base; return; }
    }
  }
  // file:// (no fetch) or an unknown layout: keep the desktop default.
}

const go = (p) => { location.hash = p; };
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const num = (n) => (n ?? 0).toLocaleString("en-US");

/* The LiveMCQ API packs the whole syllabus / instruction block into the exam
   "title" field (6.5k exams, up to ~2.3k chars). Split it into a compact
   heading plus the full text, which is shown collapsed. */
function splitTitle(s) {
  const raw = String(s ?? "").replace(/\s+/g, " ").trim();
  if (!raw) return { short: "", full: "" };
  let head = raw;
  const sep = raw.search(/-{3,}|_{3,}|={3,}|•{3,}/);   // syllabus separator
  if (sep > 0) head = raw.slice(0, sep);
  head = head.replace(/[\s\-–—_,;:]+$/, "").trim();
  if (head.length > 90) {
    const cut = head.slice(0, 90);
    const sp = cut.lastIndexOf(" ");
    head = (sp > 40 ? cut.slice(0, sp) : cut).replace(/[\s\-–—_,;:]+$/, "").trim() + "…";
  }
  const bare = head.replace(/…$/, "");
  const full = raw.length - bare.length > 40 ? raw : "";
  return { short: head || raw, full };
}
const shortTitle = (s) => splitTitle(s).short;

/* Exam title + syllabus, deduped: `t` and `s` are usually the same blob. */
function titleInfo(t, id) {
  const a = String((t && t.t) || "").replace(/\s+/g, " ").trim();
  const b = String((t && t.s) || "").replace(/\s+/g, " ").trim();
  const blob = a.length >= b.length ? a : b;
  const parts = splitTitle(blob);
  const short = (a && a.length <= 90) ? a : (parts.short || `Exam #${id}`);
  return {
    short: short || `Exam #${id}`,
    full: (parts.full && blob.length > short.length + 40) ? blob : "",
    sub: (b && b !== a && b.length <= 200) ? b : ""
  };
}
/* Turn the "----" runs the API uses as separators into real line breaks. */
function sylHTML(text) {
  return esc(text).replace(/\s*-{3,}\s*/g, "<br>");
}
function sylBlock(label, text) {
  return `<details class="syl"><summary>${esc(label)}</summary><div>${sylHTML(text)}</div></details>`;
}

function showToast(msg) {
  toast.textContent = msg;
  toast.classList.remove("hidden");
  clearTimeout(showToast._t);
  showToast._t = setTimeout(() => toast.classList.add("hidden"), 2600);
}

function render(html) { view.innerHTML = html; scrollY ? window.scrollTo({ top: 0 }) : null; }

function loadJSON(p) { return fetch(p).then(r => { if (!r.ok) throw new Error(p); return r.json(); }); }

function spin() { view.innerHTML = '<div class="center"><div class="spinner"></div></div>'; }

function setNav(name) {
  document.querySelectorAll(".bn-item").forEach(b =>
    b.classList.toggle("on", b.dataset.nav === name));
}

/* ---------------- home ---------------- */
async function home() {
  setNav("home");
  backBtn.style.visibility = "hidden";
  const [about, courses] = await Promise.all([
    loadJSON("data/about.json"), loadJSON("data/courses_index.json")]);
  window.LOCAL.about = about; window.LOCAL.courses = courses;
  topbarCount.textContent = `${num(about.exams)} exams · ${num(about.videos)} classes`;
  render(`<div class="screen">
    <div class="hero"><h1>LiveMCQ · bangla practice hub</h1>
      <p>Full offline copy of the 2026 LiveMCQ content — exams, exam papers, answer explanations, video class library and study PDFs.</p>
      <span class="hero-stat"><span class="muted" style="color:#b9c6f0">course</span> <b>${num(about.courses)}</b></span>
      <span class="hero-stat"><span class="muted" style="color:#b9c6f0">exam</span> <b>${num(about.exams)}</b></span>
      <span class="hero-stat"><span class="muted" style="color:#b9c6f0">question</span> <b>${num(about.questions)}</b></span>
      <span class="hero-stat"><span class="muted" style="color:#b9c6f0">class</span> <b>${num(about.videos)}</b></span>
    </div>
    <div class="section-title"><h2>All Courses</h2><span class="muted" style="font-size:12.5px">${num(about.pdfs)} study PDFs · ${num(about.media)} media</span></div>
    <div class="course-grid">
      ${courses.map(c => `<div class="course-card" onclick="go('#/course/${c.id}')">
        <div class="cc-head"><span class="cc-name">${esc(c.name)}</span></div>
        <div class="cc-body"><span><b>${num(c.exams)}</b> exams</span><span><b>${num(c.questions)}</b> questions</span></div>
      </div>`).join("")}
    </div>
    <div class="foot">Recovered from the LiveMCQ app/API, authorized ref LMCQ-DR-2026-1006 · viewer$ v1 · 100% offline</div>
  </div>`);
}

/* ---------------- routine (the app's daily-routine tab) ---------------- */
async function routine() {
  setNav("routine");
  backBtn.style.visibility = "visible";
  const [list] = await Promise.all([loadJSON("data/routine.json").catch(() => [])]);
  const byDate = (a, b) => (b.iso || "").localeCompare(a.iso || "") || b.id - a.id;
  const sorted = [...list].sort(byDate);
  const have = sorted.filter(r => r.has), locked = sorted.filter(r => !r.has);
  topbarCount.textContent = `${list.length} routine exams`;
  render(`<div class="screen">
    <div class="section-title"><h2>Routine</h2>
      <span class="muted" style="font-size:12.5px">${list.length} routine exams · ${have.length} with content · newest first</span></div>
    ${have.map((e, i) => rRow(e, i + 1)).join("") || '<div class="empty">No routine exams.</div>'}
    ${locked.length ? `<div style="margin-top:22px" class="section-title"><h3>Locked in the API</h3>
      <span class="muted" style="font-size:12.5px">${locked.length} routine exams return no question content</span></div>
      ${locked.map(e => rRow(e, null)).join("")}` : ""}
  </div>`);
}
function rRow(e, pos) {
  const badges = [];
  if (e.today) badges.push('<span class="pill pill-today">Today</span>');
  if (!e.has) badges.push('<span class="pill pill-lock">Locked</span>');
  return `<div class="exam-row ${e.has ? "" : "locked"}" ${e.has ? `onclick="go('#/exam/${e.id}')"` : ""}>
    <div class="mid">
      <h3>${e.title ? esc(shortTitle(e.title)) : `Routine exam #${e.id}`}</h3>
      <div class="meta">
        ${e.date ? `<span class="meta-date">📅 ${esc(e.date)}</span>` : ""}
        ${e.subj ? `<span>${esc(e.subj)}</span>` : ""}
        <span>${num(e.qn)} questions</span>
        ${e.mark ? `<span>${esc(e.mark)} marks</span>` : ""}
        ${e.time ? `<span>⏱ ${esc(e.time)}</span>` : ""}
        ${badges.join("")}
        ${pos != null ? `<span>#${pos}</span>` : ""}
      </div>
    </div>
    <span class="chev">›</span>
  </div>`;
}

/* ---------------- course -> exam list ---------------- */
async function course(id) {
  setNav("home");
  backBtn.style.visibility = "visible";
  const [about, courses, exams] = await Promise.all([
    loadJSON("data/about.json"), loadJSON("data/courses_index.json"),
    loadJSON(`data/exams_${id}.json`)]);
  const c = courses.find(x => x.id === id);
  topbarCount.textContent = esc(c ? c.name : "");
  const byDate = (a, b) => dateMs(b.date) - dateMs(a.date) || b.id - a.id;
  const rows = [...exams].sort(byDate);
  render(`<div class="screen">
    <div class="section-title"><h2>${esc(c.name)}</h2>
      <span class="muted" style="font-size:12.5px">${num(c.exams)} exams · newest first</span></div>
    ${rows.map((e, i) => examRow(e, i + 1)).join("") || '<div class="empty">No exams in this course.</div>'}
  </div>`);
}

function fmtDate(d) {
  if (!d) return null;
  const x = new Date(d);
  if (isNaN(x)) return null;
  return { d: x.getDate(), m: x.toLocaleString("en", { month: "short" }), y: x.getFullYear() };
}
function dateMs(s) {
  if (!s) return 0;
  const t = Date.parse(String(s).replace(/(\d+)(st|nd|rd|th)\b/, "$1"));
  return isNaN(t) ? 0 : t;
}
function examRow(e, pos) {
  const f = fmtDate(e.date);
  const badges = [];
  if (e.omr) badges.push('<span class="pill pill-omr">OMR</span>');
  if (!e.has) badges.push('<span class="pill pill-lock">Locked</span>');
  const dateTxt = f ? `${f.d} ${f.m} ${f.y}` : null;
  return `<div class="exam-row ${e.has ? "" : "locked"}" onclick="go('#/exam/${e.id}')">
    <div class="mid">
      <h3>${e.title ? esc(shortTitle(e.title)) : `Exam #${e.id}`}</h3>
      <div class="meta">
        ${dateTxt ? `<span class="meta-date">📅 ${dateTxt}</span>` : ""}
        <span>${num(e.qn)} questions</span>${badges.join("")}
        ${pos != null ? `<span>#${pos}</span>` : ""}
      </div>
    </div>
    <span class="chev">›</span>
  </div>`;
}

/* ---------------- exam taking ---------------- */
const T = { questions: [], idx: 0, picks: [], revealed: false, timer: null, sec: 0, started: false };

async function exam(id, review) {
  setNav("home");
  backBtn.style.visibility = "visible";
  topbarCount.textContent = `Exam #${id}`;
  let raw;
  try { raw = await loadJSON(`${BASE}/exam_maps/exam_${id}.json`); }
  catch (e) { render(lockPanel(id)); return; }
  if (!raw || !raw.question_text) { render(lockPanel(id)); return; }
  if (!window.LOCAL.titles) {
    try { window.LOCAL.titles = await loadJSON("data/exam_titles.json"); }
    catch (e2) { window.LOCAL.titles = {}; }
  }
  if (!window.LOCAL.titles) window.LOCAL.titles = {};
  const t = window.LOCAL.titles[String(id)] || { t: "", s: "" };
  const ti = titleInfo(t, id);
  topbarCount.textContent = ti.short;
  const qs = [];
  const groups = raw.question_text || {};
  for (const [g, list] of Object.entries(groups)) {
    (list || []).forEach((q) => {
      if (!q || !q.question) return;
      const ans = parseInt(q.answer, 10);
      qs.push({ g: g || "Group", ...q, answer: Number.isNaN(ans) ? 0 : ans });
    });
  }
  if (!qs.length) { render(lockPanel(id, "Paper has no readable questions.")); return; }
  Object.assign(T, { questions: qs, idx: 0, picks: new Array(qs.length).fill(null), revealed: false, started: false, title: ti.short, syl: ti.sub, ti: ti });
  if (review) mountReview();
  else examIntro(id, raw, ti);
}

function lockPanel(id, msg) {
  return `<div class="screen locked-panel"><div class="qindex">EXAM #${id}</div>
    <h2>${msg || "This exam is locked"}</h2>
    <p class="muted">The server returned a locked / paywall response for this exam and no question content is available.</p>
    <button class="btn btn-ghost" onclick="history.back()">Go back</button></div>`;
}

function examIntro(id, raw, ti) {
  const tm = raw.exam_time ? (raw.exam_time / 60000).toFixed(0) : null;
  const n = T.questions.length;
  render(`<div class="screen exam-head">
    <div class="qindex">EXAM #${id}</div>
    <h2>${esc(ti.short)}</h2>
    ${ti.sub ? `<p class="muted" style="margin:6px 0 10px;font-size:13.5px">${esc(ti.sub)}</p>` : ""}
    <div class="meta">
      <span><b>${n}</b> questions</span>
      <span>${Object.keys(raw.question_text).length} sections</span>
      ${tm ? `<span class="timer">⏱ ${tm} min</span>` : ""}
      ${raw.is_omr ? '<span class="pill pill-omr">OMR</span>' : ""}
    </div>
    <p class="muted" style="margin:10px 0 0;font-size:14px">Answer each question, then see the correct answer and full explanation instantly. Your score is tallied at the end.</p>
    ${ti.full ? sylBlock("Syllabus & instructions", ti.full) : ""}
    <div style="margin-top:18px;display:flex;gap:10px;flex-wrap:wrap">
      <button class="btn btn-primary" onclick="startExam()">Start test</button>
      <button class="btn btn-ghost" onclick="go('#/exam/${id}/review')">Review all answers</button>
  </div>`);
}
window.startExam = startExam;

function startExam() {
  T.started = true; T.revealed = false;
  clearInterval(T.timer);
  T.sec = 0;
  T.timer = setInterval(() => {
    T.sec++;
    const el = document.getElementById("clock");
    if (el) { const m = Math.floor(T.sec / 60), s = T.sec % 60; el.textContent = `⏱ ${m}:${String(s).padStart(2, "0")}`; }
  }, 1000);
  mountQuestion();
}

function mountQuestion() {
  const q = T.questions[T.idx];
  const key = T.revealed ? q.answer : null;
  const sel = T.picks[T.idx];
  const progress = ((T.idx) / T.questions.length * 100).toFixed(1);
  render(`<div class="screen">
    <div class="exam-head"><h2>${esc(q.g)}</h2>
      <div class="meta"><span class="timer" id="clock">${T.started ? "⏱ 0:00" : "⏱ —"}</span>
        <span>question ${T.idx + 1} / ${T.questions.length}</span></div>
      <div class="progress"><div style="width:${progress}%"></div></div>
    </div>
    <div class="qcard">
      <div class="qindex">QUESTION ${T.idx + 1}</div>
      <div class="qtext">${esc(q.question)}</div>
      ${[1, 2, 3, 4].map(i => optHTML(q, i, key, sel)).join("")}
      ${T.revealed ? explainHTML(q, sel) : ""}
      <div class="qnav">
        <button class="btn btn-ghost" ${T.idx === 0 ? "disabled" : ""} onclick="prevQ()">‹ Prev</button>
        <span class="qcounter">${T.idx + 1} / ${T.questions.length}</span>
        <button class="btn btn-primary" ${T.idx === T.questions.length - 1 ? "disabled" : ""} onclick="nextQ()">Next ›</button>
      </div>
      ${T.idx === T.questions.length - 1 ? '<button class="btn btn-primary" style="width:100%;margin-top:10px" onclick="finishExam()">Finish — see score</button>' : ""}
    </div>
  </div>`);
}

const KEYS = ["A", "B", "C", "D", "E"];
function optHTML(q, i, key, sel) {
  const txt = q[`option${i}`];
  if (!txt) return "";
  let cls = "opt disabled";
  if (key !== null) {
    if (i === key) cls += " right";
    else if (i === sel) cls += " wrong";
  } else {
    cls = `opt ${sel === i ? "sel" : ""}`;
  }
  return `<div class="${cls}" ${key === null ? `onclick="pick(${i})"` : ""}>
    <span class="key">${KEYS[i - 1]}</span><span>${esc(txt)}</span>${key !== null && i === key ? ' <span class="pill pill-ok" style="margin-left:auto;background:var(--ok);color:#fff">Correct</span>' : ""}
  </div>`;
}
function explainHTML(q, sel) {
  const right = q.answer;
  const ansTxt = right ? (q[`option${right}`] || "—") : "Question cancelled — no answer key";
  const status = right ? (sel === right ? "✅ Correct" : (sel == null ? "Skipped" : "✖ Wrong")) : "Cancelled";
  return `<div class="explain"><h4>${status} — Answer: ${esc(ansTxt)}</h4>${localImg(q.exp) || '<p class="muted">No explanation available.</p>'}</div>`;
}
function localImg(html) {
  if (!html || !MEDIA_URL) return html;
  return html.replace(/src=["'](https?:\/\/[^"']+)["']/g, (m, u) => {
    const r = MEDIA_URL[u];
    return r ? `src="${mediaURL(r)}"` : m;
  });
}
window.pick = function (i) {
  if (T.revealed) return;
  T.picks[T.idx] = i; T.revealed = true; mountQuestion();
};
window.prevQ = function () { if (T.idx > 0) { T.idx--; T.revealed = T.picks[T.idx] !== null; mountQuestion(); } };
window.nextQ = function () { if (T.idx < T.questions.length - 1) { T.idx++; T.revealed = false; mountQuestion(); } };
function finishExam() {
  clearInterval(T.timer);
  const qs = T.questions;
  const right = qs.filter((q, i) => q.answer && T.picks[i] === q.answer).length;
  const wrong = qs.filter((q, i) => q.answer && T.picks[i] != null && T.picks[i] !== q.answer).length;
  const skip = qs.length - right - wrong;
  const pct = qs.length ? Math.round(right / qs.length * 100) : 0;
  render(`<div class="screen">
    <div class="result-summary">
      <div class="result-score">${right} / ${qs.length}</div>
      <div class="result-label">${pct}% correct</div>
      <div class="result-details"><span>✅ ${right} right</span><span>✖ ${wrong} wrong</span><span>— ${skip} skipped</span></div>
    </div>
    <div style="display:flex;gap:10px;margin-bottom:18px;flex-wrap:wrap">
      <button class="btn btn-primary" onclick="startExam()">Retake</button>
      <button class="btn btn-ghost" onclick="reviewAll()">Review answers</button>
    </div>
    ${qs.map((q, i) => `<div class="review-item">
      <span class="qindex">Q${i + 1} · ${esc(q.g)}</span>
      <div class="q">${esc(q.question)}</div>
      <div class="a">${T.picks[i] === q.answer ? "✅ You: " : "✖ You: "}<b>${KEYS[(T.picks[i] || 0) - 1] || "—"}</b> · Correct: <b>${q.answer ? KEYS[q.answer - 1] : "—"}</b> — ${esc(q.answer ? (q[`option${q.answer}`] || "—") : "cancelled")}</div>
    </div>`).join("")}
  </div>`);
}
window.finishExam = finishExam;
window.reviewAll = reviewAll;
function reviewAll() {
  T.revealed = true;
  mountReview();
}
function mountReview() {
  const qs = T.questions;
  render(`<div class="screen"><div class="section-title"><h2>All answers</h2><span class="muted" style="font-size:12px">${qs.length} questions</span></div>
    ${qs.map((q, i) => `<div class="review-item"><span class="qindex">Q${i + 1} · ${esc(q.g)}</span>
      <div class="q">${esc(q.question)}</div>
      <div class="review-right">${[1, 2, 3, 4].map(k => optHTML(q, k, q.answer, null)).join("")}</div>
      ${explainHTML(q, null)}
    </div>`).join("")}
  </div>`);
}

/* ---------------- search ---------------- */
async function search() {
  setNav("search");
  const [courses, bankShard] = await Promise.all([
    loadJSON("data/courses_index.json"),
    loadJSON("data/search/search_bank.json")]);
  window.LOCAL.bank = bankShard;
  render(`<div class="screen">
    <div class="search-box">
      <div class="search-field"><span class="s">🔍</span>
        <input id="q" type="search" placeholder="Search questions…  e.g.  সঞ্চারপথ" autocomplete="off">
      </div>
      <div class="scope" id="scope"></div>
      <div class="search-meta" id="smeta"></div>
    </div>
    <div id="results"></div>
  </div>`);
  const scopeEl = document.getElementById("scope");
  const mkChip = (id, label, on) => `<span class="scope-chip ${on ? "on" : ""}" data-s="${id}">${esc(label)}</span>`;
  scopeEl.innerHTML = mkChip("bank", "All questions", true) +
    mkChip("routine", "Routine", false) +
    courses.map(c => mkChip(c.id, c.name, false)).join("");
  scopeEl.addEventListener("click", (e) => {
    const chip = e.target.closest(".scope-chip");
    if (!chip) return;
    scopeEl.querySelectorAll(".scope-chip").forEach(x => x.classList.toggle("on", x === chip));
    runSearch();
  });
  const input = document.getElementById("q");
  let deb = null;
  input.addEventListener("input", () => { clearTimeout(deb); deb = setTimeout(runSearch, 140); });
  input.focus();
}

async function scopeData() {
  const sel = document.querySelector(".scope-chip.on");
  const sid = sel ? sel.dataset.s : "bank";
  if (sid === "bank") return window.LOCAL.bank;
  if (!window.LOCAL._shard) window.LOCAL._shard = {};
  if (!window.LOCAL._shard[sid]) window.LOCAL._shard[sid] = await loadJSON(`data/search/search_${sid}.json`);
  return window.LOCAL._shard[sid];
}

async function runSearch() {
  const q = document.getElementById("q").value.trim();
  const res = document.getElementById("results");
  const meta = document.getElementById("smeta");
  if (!q) { res.innerHTML = ""; meta.textContent = "Type to search — bank of 80k+ and every exam question."; return; }
  meta.textContent = "Searching…";
  let data;
  try { data = await scopeData(); } catch (e) { meta.textContent = "No local shard for this scope."; return; }
  const ql = q.toLowerCase();
  const hits = [];
  for (let i = 0; i < data.length; i++) {
    const it = data[i];
    const idx = (it.q || "").toLowerCase().indexOf(ql);
    const idxo = idx < 0 ? (it.o.join(" ").toLowerCase().indexOf(ql)) : idx;
    if (idxo >= 0) hits.push({ it, idx: idx >= 0 ? idx : idxo, text: it.q + " " + it.o.join(" ") });
    if (hits.length >= 200) break;
  }
  meta.textContent = `${hits.length.toLocaleString()} matching from ${data.length.toLocaleString()} questions`;
  if (!hits.length) { res.innerHTML = '<div class="empty">No matches.</div>'; return; }
  res.innerHTML = hits.map(h => `<div class="srow" data-i="${hits.indexOf(h)}">
    <div class="q">${hl(h.it.q, ql)}</div>
    <div class="o">${(h.it.o || []).map(t => t ? `<span>${esc(t)}</span>` : "").join("")}</div>
    <div class="x" style="display:none"></div>
  </div>`).join("");
  res.querySelectorAll(".srow").forEach(row => {
    row.addEventListener("click", () => row.classList.toggle("expanded"));
  });
}
function hl(text, ql) {
  const i = (text || "").toLowerCase().indexOf(ql);
  if (i < 0) return esc(text);
  return esc(text.slice(0, i)) + "<mark>" + esc(text.slice(i, i + ql.length)) + "</mark>" + esc(text.slice(i + ql.length));
}

/* ---------------- videos ---------------- */
async function videos() {
  setNav("videos");
  const vid = await loadJSON("data/videos_index.json");
  backBtn.style.visibility = "visible";
  topbarCount.textContent = `${vid.reduce((a, s) => a + s.videos.length, 0)} classes`;
  render(`<div class="screen">
    <div class="section-title"><h2>Video Classes</h2>
      <span class="muted" style="font-size:12.5px">${vid.length} series</span></div>
    ${vid.map(s => `<div class="acc" id="acc-${s.s.id}">
      <div class="acc-head" onclick="accToggle(this)">
        <span class="arr">▶</span><span class="tt">${esc(s.s.title)}</span><span class="n">${s.videos.length}</span>
      </div>
      <div class="acc-body">${s.videos.map(v => vRow(v)).join("")}</div>
    </div>`).join("")}
    <div class="foot">Stream URLs recovered from the LiveMCQ API (CDN is unauthenticated / token-free). Play streams online, or download with <code>scripts/download_videos.sh</code> and they play from local disk.</div>
  </div>`);
}
window.accToggle = function (head) {
  head.parentElement.classList.toggle("open");
};
function vRow(v) {
  const rel = v.th ? MEDIA_URL[v.th] : null;
  const dur = v.dur || "";
  const date = v.date || "";
  const st = STREAMS[v.id];
  const rends = (st ? st.renditions : []).slice().sort((a, b) => (a.size || 0) - (b.size || 0));
  const play = rends.map(r => `<span class="vplay" onclick="event.stopPropagation();vOpen('${v.id}','${esc(r.rendition || "")}')">▶ ${esc(r.rendition || r.quality || "video")}</span>`).join("");
  return `<div class="vrow">
    <div class="thumb">${rel ? `<img src="${mediaURL(rel)}" loading="lazy" alt="">` : '<span class="ph">▶</span>'}</div>
    <div class="vi">
      <h4>${esc(v.t)}</h4>
      <div class="meta"><span>${esc(date)}</span>${dur ? `<span>⏱ ${esc(dur)}</span>` : ""}
        ${v.free ? '<span class="pill pill-free">Free</span>' : '<span class="pill pill-premium">Premium</span>'}</div>
      <div class="mets">${v.p ? `<span class="vpdf" onclick="event.stopPropagation();openPdf('${esc(v.p).replace(/'/g, "\\'")}')">📄 PDF notes</span>` : ""}${play || '<span class="vlock">▶ stream not resolved</span>'}</div>
    </div>
  </div>`;
}
window.vOpen = async function (id, rendition) {
  const st = STREAMS[id];
  if (!st || !st.renditions.length) { showToast("No stream URL recovered for this video."); return; }
  let r = st.renditions.find(x => x.rendition === rendition) || st.renditions.find(x => x.rendition === "360p") || st.renditions[0];
  // prefer a locally downloaded copy (media/videos/<id>/<file>) if present
  let src = r.url;
  const localRel = "videos/" + id + "/" + r.file;
  try {
    const hr = await fetch(mediaURL(localRel), { method: "HEAD", cache: "no-store" });
    if (hr.ok || hr.status === 206) src = mediaURL(localRel);
  } catch (e) { /* not downloaded — stream from the CDN */ }
  const vm = document.getElementById("vidModal");
  const frame = document.getElementById("vidModalFrame");
  const title = document.getElementById("vidModalTitle");
  title.textContent = (st.base || "").split("/").pop() || r.file;
  document.getElementById("vidModalSrc").textContent = src;
  document.getElementById("vidModalSrc").href = src;
  frame.src = src;
  vm.classList.remove("hidden");
};

/* ---------------- pdfs ---------------- */
async function pdfs() {
  setNav("pdfs");
  const pdfsList = await loadJSON("data/pdfs_index.json");
  backBtn.style.visibility = "visible";
  topbarCount.textContent = `${pdfsList.length} PDFs`;
  render(`<div class="screen">
    <div class="section-title"><h2>Study PDF Library</h2></div>
    <div class="pdf-count">${pdfsList.length.toLocaleString()} PDF &amp; DOCX handouts — open straight from local disk.</div>
    <div class="search-field" style="margin-bottom:14px"><span class="s">🔍</span>
      <input id="pfilter" type="search" placeholder="Filter by name…" autocomplete="off"></div>
    <div id="prows"></div>
  </div>`);
  const el = document.getElementById("prows");
  const draw = (f) => {
    const list = f ? pdfsList.filter(p => p.n.toLowerCase().includes(f)) : pdfsList;
    el.innerHTML = list.map(p => `<div class="prow" onclick="openPdfFile('${esc(p.u).replace(/'/g, "\\'")}')">
      <span class="ic">📄</span><span class="nm">${esc(p.n)}</span><span class="sz">${(p.sz / 1024).toFixed(0)} KB</span>
    </div>`).join("") || '<div class="empty">Nothing matches.</div>';
  };
  draw("");
  let deb;
  document.getElementById("pfilter").addEventListener("input", (e) => {
    clearTimeout(deb); deb = setTimeout(() => draw(e.target.value.trim().toLowerCase()), 120);
  });
}

function resolvePdf(url) {
  const rel = MEDIA_URL[url];
  if (!rel) return null;
  return mediaURL(rel);
}
/* Android WebView has no built-in PDF engine, so an <iframe> pointing straight
   at a .pdf renders blank there. Bundle pdf.js and hand it the same absolute
   URL the <img> tags already use. Desktop benefits too (consistent UI, works
   in browsers with the PDF plugin disabled). */
let HAVE_PDFJS = false;
function pdfViewerSrc(rel) {
  const abs = new URL(mediaURL(rel), location.href).href;
  return "pdfjs/web/viewer.html?file=" + encodeURIComponent(abs);
}
function openPdfFile(url) {
  const rel = MEDIA_URL[url];
  if (!rel) { showToast("File not on disk."); return; }
  pdfFrame.src = HAVE_PDFJS ? pdfViewerSrc(rel) : mediaURL(rel);
  pdfModalTitle.textContent = rel.split("/").pop();
  pdfModal.classList.remove("hidden");
}
window.openPdf = openPdfFile;
window.openPdfFile = openPdfFile;
document.getElementById("pdfModalClose").addEventListener("click", () => {
  pdfFrame.src = "";
  pdfModal.classList.add("hidden");
});
pdfModal.addEventListener("click", (e) => { if (e.target === pdfModal) { pdfFrame.src = ""; pdfModal.classList.add("hidden"); } });

/* ---------------- video modal ---------------- */
const vidModal = document.getElementById("vidModal");
const vidFrame = document.getElementById("vidModalFrame");
const closeVid = () => { try { vidFrame.pause(); } catch (e) {} vidFrame.removeAttribute("src"); vidFrame.load(); vidModal.classList.add("hidden"); };
document.getElementById("vidModalClose").addEventListener("click", closeVid);
vidModal.addEventListener("click", (e) => { if (e.target === vidModal) closeVid(); });
document.addEventListener("keydown", (e) => { if (e.key === "Escape" && !vidModal.classList.contains("hidden")) closeVid(); });

/* ---------------- routing ---------------- */
backBtn.addEventListener("click", () => history.back());
window.addEventListener("hashchange", route);
async function route() {
  const h = location.hash || "#/";
  let mm = h.match(/^#\/course\/(\d+)$/);
  if (mm) return course(+mm[1]);
  if (h === "#/routine") return routine();
  mm = h.match(/^#\/exam\/(\d+)(\/review)?$/);
  if (mm) return exam(+mm[1], !!mm[2]);
  if (h.startsWith("#/search")) return search();
  if (h.startsWith("#/videos")) return videos();
  if (h.startsWith("#/pdfs")) return pdfs();
  return home();
}

(async function boot() {
  await Promise.all([
    loadJSON("data/media_url.json").then(m => { MEDIA_URL = m; }).catch(() => {}),
    loadJSON("data/video_streams.json").then(m => { STREAMS = m || {}; }).catch(() => {}),
  ]);
  await probeMediaBase();
  try {
    const r = await fetch("pdfjs/web/viewer.html", { method: "HEAD", cache: "no-store" });
    HAVE_PDFJS = r.ok;
  } catch (e) { HAVE_PDFJS = false; }
  route();
})();