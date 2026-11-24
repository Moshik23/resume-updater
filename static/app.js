// Resume Tailor front end: plain JS, no build step.
// Flow: upload -> working (background analysis, polled) -> review (marks on the
// resume, keep/skip each) -> done (downloads + change summary). Plus an
// Applications view backed by the per-profile tracker.

const MAX_RESUME_BYTES = 4 * 1024 * 1024;
const MAX_JD = 20000;
const MIN_JD = 80;
const POLL_INTERVAL_MS = 3000;
const POLL_TIMEOUT_MS = 5 * 60 * 1000;
const PROFILE_KEY = "resumeTailorProfile";

const $ = (id) => document.getElementById(id);

const state = {
  me: null,
  profile: null,
  saved: { exists: false, filename: null },
  savedBlocks: null,
  chosenFile: null,
  job: null,            // { id, blocks, gaps, edits, matched, reqCount, scoreBefore, company, title }
  kept: new Set(),      // edit_ids kept
  wording: new Map(),   // edit_id -> edited new_text
  submittedAnswers: "", // JSON of the last answers sent, to avoid resubmitting
  wantResume: true,
  wantCover: false,
  step: "upload",
};

// ---------------------------------------------------------------- helpers
function escapeHtml(str) {
  return String(str ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

function setStatus(el, message, kind) {
  el.textContent = message || "";
  if (kind) el.dataset.state = kind; else delete el.dataset.state;
}

async function errorMessage(response, fallback) {
  try {
    const body = await response.json();
    if (body && body.detail) return typeof body.detail === "string" ? body.detail : fallback;
  } catch { /* not JSON */ }
  if (response.status === 413) return "That file is too large. Keep it under 4 MB.";
  return `${fallback} (${response.status})`;
}

function storageGet(key) { try { return localStorage.getItem(key); } catch { return null; } }
function storageSet(key, value) { try { localStorage.setItem(key, value); } catch { /* private mode */ } }

function pct(value) { return value == null ? "—" : `${Math.round(value)}%`; }

const dateFmt = new Intl.DateTimeFormat("en-SG", { day: "numeric", month: "short", year: "numeric", timeZone: "Asia/Singapore" });

// ---------------------------------------------------------------- steps & views
function showStep(step) {
  state.step = step;
  document.querySelectorAll("[data-step]").forEach((el) => { el.hidden = el.dataset.step !== step; });
  const paper = $("paper");
  paper.classList.toggle("faded", step === "upload" || step === "working");
  $("scan").hidden = step !== "working";
  $("changes").hidden = step !== "done" || !$("summary-content").innerHTML;
  paper.hidden = !$("changes").hidden;
  $("paper-tag").textContent = { upload: "Your resume", working: "Reading…", review: "Suggested changes", done: "Change summary" }[step];
  if (step === "upload") renderUploadPaper();
  window.scrollTo({ top: 0 });
}

function showView(view) {
  document.querySelectorAll(".nav button").forEach((b) => b.setAttribute("aria-current", b.dataset.view === view ? "page" : "false"));
  $("view-tailor").hidden = view !== "tailor";
  $("view-apps").hidden = view !== "apps";
  if (view === "apps") loadApplications();
}

document.querySelectorAll(".nav button").forEach((b) => b.addEventListener("click", () => showView(b.dataset.view)));

// ---------------------------------------------------------------- who's signed in
async function loadMe() {
  try {
    const r = await fetch("/api/me", { cache: "no-store" });
    state.me = r.ok ? await r.json() : { locked: false, profiles: [] };
  } catch {
    state.me = { locked: false, profiles: [] };
  }
  if (state.me.locked) {
    $("who").hidden = false;
    $("who-name").textContent = `Hi, ${state.me.label}`;
    $("who-initial").textContent = (state.me.label || "?").charAt(0).toUpperCase();
    $("profile-field").hidden = true;
    await setProfile(state.me.profile);
  } else {
    renderProfilePicker();
    const remembered = storageGet(PROFILE_KEY);
    if (remembered && state.me.profiles.some((p) => p.value === remembered)) await setProfile(remembered);
  }
}

function renderProfilePicker() {
  const picker = $("profile-picker");
  picker.replaceChildren();
  $("profile-field").hidden = !state.me.profiles.length;
  for (const p of state.me.profiles) {
    const b = document.createElement("button");
    b.type = "button";
    b.setAttribute("role", "radio");
    b.setAttribute("aria-checked", String(state.profile === p.value));
    b.textContent = p.label;
    b.addEventListener("click", () => setProfile(p.value));
    picker.append(b);
  }
}

async function setProfile(profile) {
  state.profile = profile;
  state.chosenFile = null;
  if (!state.me.locked) {
    storageSet(PROFILE_KEY, profile);
    renderProfilePicker();
  }
  await loadSavedResume();
}

$("switch-person").addEventListener("click", async (e) => {
  e.preventDefault();
  // Swap the browser's remembered login for a bogus one, then reload so it asks again.
  try { await fetch("/logout", { headers: { Authorization: "Basic " + btoa("signed-out:x") }, cache: "no-store" }); } catch { /* ignore */ }
  window.location.href = "/";
});

// ---------------------------------------------------------------- resume file
async function loadSavedResume() {
  state.saved = { exists: false, filename: null };
  state.savedBlocks = null;
  if (state.profile) {
    try {
      const r = await fetch(`/api/profiles/${state.profile}/default-resume-meta`, { cache: "no-store" });
      if (r.ok) state.saved = await r.json();
      if (state.saved.exists) {
        const p = await fetch(`/api/profiles/${state.profile}/default-resume-preview`, { cache: "no-store" });
        if (p.ok) state.savedBlocks = (await p.json()).blocks;
      }
    } catch { /* offline: leave empty */ }
  }
  renderResumeField();
  if (state.step === "upload") renderUploadPaper();
}

function renderResumeField() {
  const file = state.chosenFile;
  const hasSaved = state.saved.exists;
  $("resume-card").hidden = !(file || hasSaved);
  $("dropzone").hidden = !!(file || hasSaved);
  $("drop-note").hidden = !(file || hasSaved);
  if (file) {
    $("resume-name").textContent = file.name;
    $("resume-hint").textContent = hasSaved ? "New file · replaces your saved resume when you tailor" : "New file · saved for next time when you tailor";
  } else if (hasSaved) {
    $("resume-name").textContent = state.saved.filename;
    $("resume-hint").textContent = "Saved · used for every job until you replace it";
  }
}

function acceptFile(file) {
  if (!file) return;
  const ext = (file.name.split(".").pop() || "").toLowerCase();
  if (!["docx", "pdf"].includes(ext)) {
    setStatus($("upload-status"), "That file isn't a .docx or .pdf.", "error");
    return;
  }
  if (file.size > MAX_RESUME_BYTES) {
    setStatus($("upload-status"), "That file is over 4 MB. Save it without embedded images, or as a smaller PDF.", "error");
    return;
  }
  setStatus($("upload-status"), "");
  state.chosenFile = file;
  renderResumeField();
  renderUploadPaper();
}

$("resume-file").addEventListener("change", (e) => { acceptFile(e.target.files[0]); e.target.value = ""; });
$("replace-resume").addEventListener("click", () => $("resume-file").click());

// Drop a resume anywhere on the page (upload step only)
let dragDepth = 0;
const hasFiles = (e) => [...(e.dataTransfer?.types || [])].includes("Files");
window.addEventListener("dragenter", (e) => { if (!hasFiles(e) || state.step !== "upload") return; dragDepth++; $("drop-overlay").hidden = false; });
window.addEventListener("dragleave", () => { dragDepth = Math.max(0, dragDepth - 1); if (!dragDepth) $("drop-overlay").hidden = true; });
window.addEventListener("dragover", (e) => { if (hasFiles(e)) e.preventDefault(); });
window.addEventListener("drop", (e) => {
  if (!hasFiles(e)) return;
  e.preventDefault();
  dragDepth = 0;
  $("drop-overlay").hidden = true;
  if (state.step === "upload") acceptFile(e.dataTransfer.files[0]);
});

// ---------------------------------------------------------------- job ad
const jdInput = $("job-description");
function updateCount() {
  const n = jdInput.value.length;
  const el = $("jd-count");
  el.textContent = `${n.toLocaleString("en-SG")} / 20,000`;
  el.classList.toggle("over", n > MAX_JD);
}
jdInput.addEventListener("input", updateCount);

$("fetch-job").addEventListener("click", fetchJob);
$("job-url").addEventListener("keydown", (e) => { if (e.key === "Enter") { e.preventDefault(); fetchJob(); } });

async function fetchJob() {
  const url = $("job-url").value.trim();
  const note = $("fetch-note");
  if (!url) { $("job-url").focus(); return; }
  const btn = $("fetch-job");
  btn.disabled = true; btn.textContent = "Fetching…";
  note.hidden = true; note.classList.remove("ok");
  try {
    const r = await fetch("/api/jobs/from-url", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ url }) });
    if (!r.ok) throw new Error(await errorMessage(r, "Couldn't read that link"));
    const job = await r.json();
    jdInput.value = job.description;
    updateCount();
    note.textContent = `✓ Pulled from ${job.source}. Check it below and trim anything that isn't the job.`;
    note.classList.add("ok");
  } catch (err) {
    note.textContent = err.message;
  } finally {
    note.hidden = false;
    btn.disabled = false; btn.textContent = "Fetch";
  }
}

// ---------------------------------------------------------------- the paper
function blockKind(block, index) {
  const style = (block.style_name || "").toLowerCase();
  const text = block.text.trim();
  if (style.includes("title") || (index === 0 && text.length < 60)) return "title";
  const level = style.match(/heading\s*(\d)/);
  if (level) return Number(level[1]) <= 2 ? "head" : "sub";
  if (style.includes("heading")) return "head";
  if (style.includes("list") || /^[•▪●◦\-–]\s/.test(text)) return "li";
  if (!style && text.length < 40 && text === text.toUpperCase() && /[A-Z]/.test(text)) return "head";
  return "p";
}

function stripBullet(text) { return text.replace(/^[•▪●◦\-–]\s+/, ""); }

// Word-level diff (LCS) so a mark shows only the words that change.
function wordDiff(a, b) {
  const x = a.split(/(\s+)/).filter(Boolean);
  const y = b.split(/(\s+)/).filter(Boolean);
  if (x.length * y.length > 40000) return [["del", a], ["ins", b]];
  const dp = Array.from({ length: x.length + 1 }, () => new Array(y.length + 1).fill(0));
  for (let i = x.length - 1; i >= 0; i--) for (let j = y.length - 1; j >= 0; j--) {
    dp[i][j] = x[i] === y[j] ? dp[i + 1][j + 1] + 1 : Math.max(dp[i + 1][j], dp[i][j + 1]);
  }
  const ops = [];
  const push = (op, t) => { const last = ops[ops.length - 1]; if (last && last[0] === op) last[1] += t; else ops.push([op, t]); };
  let i = 0, j = 0;
  while (i < x.length && j < y.length) {
    if (x[i] === y[j]) { push("eq", x[i]); i++; j++; }
    else if (dp[i + 1][j] >= dp[i][j + 1]) { push("del", x[i]); i++; }
    else { push("ins", y[j]); j++; }
  }
  while (i < x.length) push("del", x[i++]);
  while (j < y.length) push("ins", y[j++]);
  return ops;
}

function editText(edit) { return state.wording.get(edit.edit_id) ?? edit.new_text; }
function editNumber(edit) { return state.job.edits.indexOf(edit) + 1; }

function markClasses(edit) {
  const cls = ["mark"];
  if (edit.requires_user_input) cls.push("waiting", "off");
  else if (!state.kept.has(edit.edit_id)) cls.push("off");
  return cls.join(" ");
}

function inlineMarkHtml(edit) {
  const ops = wordDiff(edit.anchor_text, editText(edit));
  const inner = ops.map(([op, t]) => op === "eq" ? escapeHtml(t) : `<span class="${op}">${escapeHtml(t)}</span>`).join("");
  return `<span class="${markClasses(edit)}" data-e="${escapeHtml(edit.edit_id)}" role="button" tabindex="0" aria-label="Change ${editNumber(edit)}">${inner}<span class="pin">${editNumber(edit)}</span></span>`;
}

// Returns { html, placed:Set } for one block's text with inline edits applied as marks
function blockHtml(block, edits, withMarks) {
  const text = block.text;
  if (!withMarks) return { html: escapeHtml(text), placed: new Set() };
  const spans = [];
  for (const e of edits) {
    if (!["replace_phrase", "insert_keyword"].includes(e.type) || !e.anchor_text) continue;
    const at = text.indexOf(e.anchor_text);
    if (at === -1) continue;
    const end = at + e.anchor_text.length;
    if (spans.some((s) => at < s.end && end > s.start)) continue; // overlapping edits: list only
    spans.push({ start: at, end, edit: e });
  }
  spans.sort((a, b) => a.start - b.start);
  let html = "", pos = 0;
  for (const s of spans) {
    html += escapeHtml(text.slice(pos, s.start)) + inlineMarkHtml(s.edit);
    pos = s.end;
  }
  html += escapeHtml(text.slice(pos));
  return { html, placed: new Set(spans.map((s) => s.edit.edit_id)) };
}

// Word puts header tables (name, contact line) after the body when read in order.
// If the only table content is a few short lines, show it first, like on the page.
function orderBlocks(blocks) {
  const table = blocks.filter((b) => /^t\d/.test(b.id));
  if (!table.length || table.length > 6 || table.some((b) => b.text.length > 120)) return blocks;
  return [...table, ...blocks.filter((b) => !/^t\d/.test(b.id))];
}

function renderResume(rawBlocks, edits, withMarks) {
  const blocks = orderBlocks(rawBlocks);
  const byBlock = new Map();
  for (const e of edits) { if (!byBlock.has(e.block_id)) byBlock.set(e.block_id, []); byBlock.get(e.block_id).push(e); }
  const placed = new Set();
  let html = "";
  blocks.forEach((block, index) => {
    const kind = blockKind(block, index);
    const blockEdits = byBlock.get(block.id) || [];
    const shown = kind === "li" ? { ...block, text: stripBullet(block.text) } : block;
    const { html: inner, placed: got } = blockHtml(shown, blockEdits, withMarks);
    got.forEach((id) => placed.add(id));
    const cls = { title: "r-title", head: "r-head", sub: "r-sub", li: "r-li", p: "" }[kind];
    html += `<p${cls ? ` class="${cls}"` : ""}>${inner}</p>`;
    if (withMarks) {
      for (const e of blockEdits) {
        if (!["append_bullet", "new_bullet_after"].includes(e.type)) continue;
        placed.add(e.edit_id);
        const body = e.requires_user_input ? `<span class="ins pending">waiting for your answer above</span>` : `<span class="ins">${escapeHtml(editText(e))}</span>`;
        html += `<p class="r-li r-new ${markClasses(e)}" data-e="${escapeHtml(e.edit_id)}" role="button" tabindex="0" aria-label="Change ${editNumber(e)}">${body}<span class="pin">${editNumber(e)}</span></p>`;
      }
    }
  });
  return { html, placed };
}

function renderUploadPaper() {
  const paper = $("paper");
  if (state.chosenFile) {
    paper.innerHTML = `<div class="paper-empty"><b>${escapeHtml(state.chosenFile.name)}</b>We'll read it when you press Tailor.</div>`;
  } else if (state.savedBlocks && state.savedBlocks.length) {
    paper.innerHTML = renderResume(state.savedBlocks, [], false).html;
  } else {
    paper.innerHTML = `<div class="paper-empty"><b>Your resume appears here</b>${state.profile ? "Choose a .docx or .pdf on the left, or drop it on the page." : "Pick who's using this first."}</div>`;
  }
}

let unplaced = new Set();
function renderReviewPaper() {
  const { html, placed } = renderResume(state.job.blocks, state.job.edits, true);
  $("paper").innerHTML = html;
  unplaced = new Set(state.job.edits.filter((e) => !placed.has(e.edit_id)).map((e) => e.edit_id));
}

$("paper").addEventListener("click", (e) => {
  const mark = e.target.closest(".mark");
  if (mark && state.step === "review") toggleEdit(mark.dataset.e, true);
});
$("paper").addEventListener("keydown", (e) => {
  const mark = e.target.closest(".mark");
  if (mark && state.step === "review" && (e.key === "Enter" || e.key === " ")) { e.preventDefault(); toggleEdit(mark.dataset.e, true); }
});

// ---------------------------------------------------------------- submit -> working
$("upload-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const status = $("upload-status");
  const jd = jdInput.value.trim();
  state.wantResume = $("output-resume").checked;
  state.wantCover = $("output-cover-letter").checked;

  if (!state.profile) return setStatus(status, "Pick who's using this first.", "error");
  if (!state.chosenFile && !state.saved.exists) return setStatus(status, "Choose your resume first.", "error");
  if (jd.length < MIN_JD) return setStatus(status, "Paste the whole job ad, or fetch it from a link.", "error");
  if (jd.length > MAX_JD) return setStatus(status, "That job description is over 20,000 characters. Trim it to just the job ad.", "error");
  if (!state.wantResume && !state.wantCover) return setStatus(status, "Choose a tailored resume, a cover letter, or both.", "error");
  setStatus(status, "");

  const form = new FormData();
  if (state.chosenFile) form.append("resume", state.chosenFile);
  form.append("job_description", jd);
  if (!state.me.locked) form.append("profile", state.profile);

  const btn = $("tailor-button");
  btn.disabled = true;
  try {
    const r = await fetch("/api/jobs", { method: "POST", body: form });
    if (!r.ok) throw new Error(await errorMessage(r, "Couldn't start tailoring"));
    const accepted = await r.json();
    startWorking(accepted);
    const result = await waitForAnalysis(accepted.job_id);
    stopWorking();
    openReview(accepted.job_id, result);
  } catch (err) {
    stopWorking();
    if (state.step === "working") {
      setStatus($("working-status"), err.message, "error");
      $("working-back").hidden = false;
    } else {
      setStatus(status, err.message, "error");
    }
  } finally {
    btn.disabled = false;
  }
});

let workingTimer = null;
function startWorking(accepted) {
  $("working-title").textContent = "Tailoring your resume…";
  setStatus($("working-status"), "");
  $("working-back").hidden = true;
  const steps = [...$("working-steps").children];
  steps.forEach((li) => li.className = "");
  const read = steps[0];
  read.className = "done";
  read.querySelector("span:last-child").textContent = accepted.block_count ? `Read your resume · ${accepted.block_count} sections` : "Read your resume";
  steps[1].className = "now";
  if (state.chosenFile || !state.savedBlocks) $("paper").innerHTML = `<div class="paper-empty"><b>Reading your resume…</b></div>`;
  showStep("working");
  // The analysis is one call to Claude, so this is an honest-ish estimate, not live progress.
  workingTimer = setTimeout(() => { steps[1].className = "done"; steps[2].className = "now"; }, 15000);
}
function stopWorking() { clearTimeout(workingTimer); }
$("working-back").addEventListener("click", () => showStep("upload"));

async function waitForAnalysis(jobId) {
  const started = Date.now();
  while (Date.now() - started < POLL_TIMEOUT_MS) {
    await new Promise((res) => setTimeout(res, POLL_INTERVAL_MS));
    const r = await fetch(`/api/jobs/${jobId}`, { cache: "no-store" });
    if (!r.ok) throw new Error(await errorMessage(r, "Tailoring failed"));
    const body = await r.json();
    if (body.status === "done") return body;
    if (body.status === "error") throw new Error(body.detail || "Tailoring failed");
  }
  throw new Error("This is taking longer than expected. Please try again.");
}

// ---------------------------------------------------------------- review
function openReview(jobId, data) {
  state.job = {
    id: jobId,
    blocks: data.blocks || [],
    gaps: data.gaps || [],
    edits: data.suggested_edits || [],
    matched: new Set(data.matched_requirements || []),
    reqCount: data.requirement_count || 0,
    scoreBefore: data.match_score_before,
    company: data.company_name,
    title: data.job_title,
  };
  state.kept = new Set(state.job.edits.filter((e) => !e.requires_user_input).map((e) => e.edit_id));
  state.wording = new Map();
  state.submittedAnswers = "";
  state.chosenFile = null; // it's now the saved default on the server

  const where = [state.job.title, state.job.company].filter(Boolean).join(" at ");
  const n = state.job.edits.length;
  $("review-title").textContent = n ? `${n} change${n === 1 ? "" : "s"}${where ? ` for ${where}` : ""}` : `Looking good${where ? ` for ${where}` : ""}`;
  $("track-company").value = state.job.company || "";
  $("track-role").value = state.job.title || "";
  $("score-from").textContent = `from ${pct(state.job.scoreBefore)}`;
  $("score-base").style.left = `${state.job.scoreBefore || 0}%`;
  setStatus($("write-status"), "");
  setStatus($("answers-status"), "");

  renderQuestions();
  renderReview();
  showStep("review");
}

function currentScore() {
  const job = state.job;
  if (!job.reqCount) return 100;
  const covered = new Set(job.matched);
  for (const e of job.edits) if (e.related_gap && !e.requires_user_input && state.kept.has(e.edit_id)) covered.add(e.related_gap);
  return Math.round((covered.size / job.reqCount) * 1000) / 10;
}

function renderReview() {
  renderReviewPaper();
  renderEditList();
  const score = currentScore();
  $("score-now").textContent = pct(score);
  $("score-bar").style.width = `${score}%`;
  $("no-edits").hidden = state.job.edits.length > 0;
}

function sectionFor(blockId) {
  let section = "";
  const blocks = orderBlocks(state.job.blocks);
  for (let i = 0; i < blocks.length; i++) {
    const b = blocks[i];
    const kind = blockKind(b, i);
    if (kind === "head") section = b.text.trim();
    if (b.id === blockId) break;
  }
  if (!section) return "Resume";
  return section.charAt(0) + section.slice(1).toLowerCase();
}

function shorten(text, n = 70) { return text.length > n ? text.slice(0, n - 1) + "…" : text; }

function describeEdit(e) {
  if (["append_bullet", "new_bullet_after"].includes(e.type)) return `new bullet: ${shorten(editText(e))}`;
  const ops = e.anchor_text ? wordDiff(e.anchor_text, editText(e)) : [];
  const insRuns = ops.filter(([op]) => op === "ins");
  const delRuns = ops.filter(([op]) => op === "del");
  if (insRuns.length === 1 && !delRuns.length) return `add "${shorten(insRuns[0][1].trim(), 60)}"`;
  if (insRuns.length === 1 && delRuns.length === 1) return `"${shorten(delRuns[0][1].trim(), 30)}" → "${shorten(insRuns[0][1].trim(), 40)}"`;
  if (e.anchor_text) return `"${shorten(e.anchor_text, 30)}" → "${shorten(editText(e), 40)}"`;
  return shorten(editText(e));
}

function renderEditList() {
  const list = $("edit-list");
  const openWording = new Set([...list.querySelectorAll("li[data-open]")].map((li) => li.dataset.e));
  list.replaceChildren();
  state.job.edits.forEach((e, i) => {
    const li = document.createElement("li");
    li.dataset.e = e.edit_id;
    const kept = state.kept.has(e.edit_id) && !e.requires_user_input;
    const offPaper = unplaced.has(e.edit_id) ? " · not shown on the preview" : "";
    li.innerHTML = `
      <div class="edit-row">
        <span class="pin">${i + 1}</span>
        <span class="t"><b>${escapeHtml(sectionFor(e.block_id))}:</b> ${escapeHtml(describeEdit(e))}<span class="why">${escapeHtml(e.rationale)}${offPaper}</span></span>
        <span class="edit-actions">
          <button type="button" class="switch" aria-pressed="${kept}" ${e.requires_user_input ? "disabled" : ""}>${e.requires_user_input ? "Needs answer" : kept ? "Keep" : "Skip"}</button>
          ${e.requires_user_input ? "" : `<button type="button" class="wording-btn">Edit wording</button>`}
        </span>
      </div>`;
    li.querySelector(".switch").addEventListener("click", () => toggleEdit(e.edit_id, false));
    const wb = li.querySelector(".wording-btn");
    if (wb) wb.addEventListener("click", () => toggleWording(li, e));
    list.append(li);
    if (openWording.has(e.edit_id)) toggleWording(li, e);
  });
}

function toggleWording(li, e) {
  const existing = li.querySelector(".wording");
  if (existing) { existing.remove(); delete li.dataset.open; return; }
  li.dataset.open = "1";
  const box = document.createElement("div");
  box.className = "wording";
  const ta = document.createElement("textarea");
  ta.value = editText(e);
  ta.setAttribute("aria-label", `Wording for change ${editNumber(e)}`);
  let t = null;
  ta.addEventListener("input", () => {
    state.wording.set(e.edit_id, ta.value);
    clearTimeout(t);
    t = setTimeout(renderReviewPaper, 250);
  });
  box.append(ta);
  li.append(box);
}

function toggleEdit(editId, fromPaper) {
  const e = state.job.edits.find((x) => x.edit_id === editId);
  if (!e || e.requires_user_input) {
    if (e && fromPaper) document.querySelector(`#questions textarea[data-req="${CSS.escape(e.related_gap || "")}"]`)?.focus();
    return;
  }
  if (state.kept.has(editId)) state.kept.delete(editId); else state.kept.add(editId);
  renderReview();
  if (fromPaper) document.querySelector(`#edit-list li[data-e="${CSS.escape(editId)}"]`)?.scrollIntoView({ block: "nearest", behavior: "smooth" });
}

// ---------- gap questions
function renderQuestions() {
  const gaps = state.job.gaps;
  $("questions-block").hidden = !gaps.length;
  $("questions-title").textContent = gaps.length === 1 ? "1 question only you can answer" : `${gaps.length} questions only you can answer`;
  const box = $("questions");
  box.replaceChildren();
  for (const g of gaps) {
    const div = document.createElement("div");
    div.className = "q";
    div.innerHTML = `<p><b>${escapeHtml(g.requirement)}</b>: ${escapeHtml(g.question_to_user)}</p>`;
    const ta = document.createElement("textarea");
    ta.dataset.req = g.requirement;
    ta.placeholder = "Your answer, in a sentence. Leave blank to skip.";
    ta.setAttribute("aria-label", g.question_to_user);
    ta.addEventListener("input", () => { $("use-answers").hidden = !collectAnswers().length || JSON.stringify(collectAnswers()) === state.submittedAnswers; });
    div.append(ta);
    box.append(div);
  }
  $("use-answers").hidden = true;
}

function collectAnswers() {
  return [...$("questions").querySelectorAll("textarea")]
    .map((ta) => ({ requirement: ta.dataset.req, answer: ta.value.trim() }))
    .filter((a) => a.answer);
}

async function submitAnswers() {
  const answers = collectAnswers();
  const key = JSON.stringify(answers);
  if (!answers.length || key === state.submittedAnswers) return;
  const status = $("answers-status");
  const btn = $("use-answers");
  btn.disabled = true;
  setStatus(status, "Adding your answers…");
  try {
    const r = await fetch(`/api/jobs/${state.job.id}/answers`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ answers }) });
    if (!r.ok) throw new Error(await errorMessage(r, "Couldn't add your answers"));
    const data = await r.json();
    const before = new Map(state.job.edits.map((e) => [e.edit_id, e.requires_user_input]));
    state.job.edits = data.suggested_edits;
    for (const e of state.job.edits) {
      if (before.get(e.edit_id) && !e.requires_user_input) { state.kept.add(e.edit_id); state.wording.delete(e.edit_id); }
    }
    state.submittedAnswers = key;
    renderReview();
    btn.hidden = true;
    setStatus(status, "Added. Check the new marks on your resume.", "success");
  } catch (err) {
    setStatus(status, err.message, "error");
    throw err;
  } finally {
    btn.disabled = false;
  }
}
$("use-answers").addEventListener("click", () => submitAnswers().catch(() => {}));

$("track-application").addEventListener("change", (e) => { $("track-fields").hidden = !e.target.checked; });

// ---------------------------------------------------------------- write -> done
$("write-button").addEventListener("click", async () => {
  const btn = $("write-button");
  const status = $("write-status");
  btn.disabled = true;
  try {
    await submitAnswers();
    setStatus(status, state.wantResume && state.wantCover ? "Writing your resume and cover letter…" : state.wantCover ? "Writing your cover letter…" : "Writing your resume…");
    const accepted = state.job.edits
      .filter((e) => !e.requires_user_input && state.kept.has(e.edit_id))
      .map((e) => ({ ...e, new_text: editText(e) }));
    const r = await fetch(`/api/jobs/${state.job.id}/apply`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        accepted_edits: accepted,
        include_resume: state.wantResume,
        include_cover_letter: state.wantCover,
        profile: state.me.locked ? null : state.profile,
        track_application: $("track-application").checked,
        company_name: $("track-company").value.trim() || null,
        job_title: $("track-role").value.trim() || null,
      }),
    });
    if (!r.ok) throw new Error(await errorMessage(r, "Couldn't write your resume"));
    setStatus(status, "");
    openDone(await r.json(), accepted.length);
  } catch (err) {
    setStatus(status, err.message, "error");
  } finally {
    btn.disabled = false;
  }
});

let lastSummary = null;
function openDone(data, keptCount) {
  const where = state.job.company ? ` for ${state.job.company}` : "";
  $("done-title").textContent = `Ready${where}.`;
  const hasScore = data.match_score_after != null;
  $("done-score").hidden = !hasScore;
  if (hasScore) {
    $("done-score-now").textContent = pct(data.match_score_after);
    $("done-score-from").textContent = `from ${pct(data.match_score_before)}`;
  }
  const failed = (data.failed_edit_ids || []).length;
  const skipped = state.job.edits.length - keptCount;
  const bits = [];
  if (state.wantResume) bits.push(`${keptCount - failed} change${keptCount - failed === 1 ? "" : "s"} applied`);
  if (skipped > 0 && state.wantResume) bits.push(`${skipped} skipped`);
  if (failed) bits.push(`${failed} couldn't be placed automatically (see the summary)`);
  $("done-note").textContent = bits.join(" · ");

  const link = (id, url) => { const a = $(id); a.hidden = !url; if (url) a.href = url; };
  link("download-resume", data.download_url);
  link("download-cover", data.cover_letter_download_url);
  link("download-summary", data.summary_download_url);
  $("tracked-note").hidden = !$("track-application").checked;

  lastSummary = data.summary_markdown || null;
  $("summary-content").innerHTML = lastSummary ? renderSummaryMarkdown(lastSummary, $("checklist-toggle").checked) : "";
  showStep("done");
}

$("checklist-toggle").addEventListener("change", () => {
  if (lastSummary) $("summary-content").innerHTML = renderSummaryMarkdown(lastSummary, $("checklist-toggle").checked);
});

document.querySelectorAll("[data-restart]").forEach((b) => b.addEventListener("click", async () => {
  state.job = null;
  jdInput.value = ""; updateCount();
  $("job-url").value = ""; $("fetch-note").hidden = true;
  $("summary-content").innerHTML = "";
  showStep("upload");
  await loadSavedResume();
}));

// ---------------------------------------------------------------- applications
async function loadApplications() {
  const body = $("apps-body");
  body.replaceChildren();
  $("apps-table").hidden = true;
  $("apps-empty").hidden = true;
  if (!state.profile) { $("apps-empty").textContent = "Pick who's using this on the Tailor tab first."; $("apps-empty").hidden = false; return; }
  try {
    const r = await fetch(`/api/profiles/${state.profile}/tracker`, { cache: "no-store" });
    const entries = r.ok ? await r.json() : [];
    if (!entries.length) {
      $("apps-empty").textContent = 'Nothing yet. Tailor a resume and tick "Add to my applications".';
      $("apps-empty").hidden = false;
      return;
    }
    for (const e of entries) {
      const tr = document.createElement("tr");
      const match = e.match_score_before != null && e.match_score_after != null
        ? `${Math.round(e.match_score_before)} → ${Math.round(e.match_score_after)}%`
        : e.match_score_before != null ? `${Math.round(e.match_score_before)}%` : "—";
      tr.innerHTML = `<td>${escapeHtml(e.company_name || "—")}</td><td>${escapeHtml(e.job_title || "—")}</td><td>${escapeHtml(dateFmt.format(new Date(e.tracked_at)))}</td><td class="num">${escapeHtml(match)}</td>`;
      body.append(tr);
    }
    $("apps-table").hidden = false;
  } catch {
    $("apps-empty").textContent = "Couldn't load your applications. Try again in a moment.";
    $("apps-empty").hidden = false;
  }
}

// Renders the small, controlled markdown subset that app/summary.py emits
// (# / ## headings, "- " bullets with one level of nested "  - " bullets,
// and **bold**). Not a general-purpose markdown parser.
//
// When withCheckboxes is true, each top-level bullet (one applied change,
// gap, or matched requirement) is wrapped in a checkbox label so a user
// editing their resume by hand can tick items off as they go. Detail
// bullets nested under a top-level item stay outside the checkbox label —
// only the top-level item itself is checkable.
function renderSummaryMarkdown(markdown, withCheckboxes) {
  const lines = markdown.split("\n").map((line) => line.trimEnd());
  let html = "";
  let inTopList = false;
  let inNestedList = false;
  let topItemOpen = false;
  let topLabelOpen = false;

  const closeTopLabel = () => {
    if (topLabelOpen) {
      html += "</span></label>";
      topLabelOpen = false;
    }
  };
  const closeNestedList = () => {
    if (inNestedList) {
      html += "</ul>";
      inNestedList = false;
    }
  };
  const closeTopItem = () => {
    closeNestedList();
    closeTopLabel();
    if (topItemOpen) {
      html += "</li>";
      topItemOpen = false;
    }
  };
  const closeTopList = () => {
    closeTopItem();
    if (inTopList) {
      html += "</ul>";
      inTopList = false;
    }
  };

  const inlineFormat = (text) =>
    escapeHtml(text).replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>");

  for (const line of lines) {
    if (line.startsWith("# ")) {
      closeTopList();
      continue; // top-level title is already shown as the section heading
    }
    if (line.startsWith("## ")) {
      closeTopList();
      html += `<h2>${inlineFormat(line.slice(3))}</h2>`;
      continue;
    }
    const nestedMatch = line.match(/^ {2}- (.*)$/);
    const topMatch = line.match(/^- (.*)$/);
    if (nestedMatch) {
      closeTopLabel(); // detail bullets sit outside the checkbox label
      if (!inNestedList) {
        html += "<ul>";
        inNestedList = true;
      }
      html += `<li>${inlineFormat(nestedMatch[1])}</li>`;
    } else if (topMatch) {
      closeTopItem();
      if (!inTopList) {
        html += "<ul>";
        inTopList = true;
      }
      if (withCheckboxes) {
        html += `<li><label class="checklist-item"><input type="checkbox" /><span>${inlineFormat(topMatch[1])}`;
        topLabelOpen = true;
      } else {
        html += `<li>${inlineFormat(topMatch[1])}`;
      }
      topItemOpen = true;
    }
  }
  closeTopList();
  return html;
}

// ---------------------------------------------------------------- start
updateCount();
showStep("upload");
loadMe();
