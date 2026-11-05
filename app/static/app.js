/* Tashkhees SPA — vanilla JS, no build step.
   Talks to the FastAPI backend with a Bearer JWT held in localStorage. */

const API = "";
const TOKEN_KEY = "tashkhees.token";
const USER_KEY = "tashkhees.user";

const state = {
  token: localStorage.getItem(TOKEN_KEY) || "",
  user: safeParse(localStorage.getItem(USER_KEY)),
  studies: [],
  current: null,
  analysis: null,
  report: null,
  file: null,
};

/* ---------------- helpers ---------------- */

function safeParse(s) { try { return s ? JSON.parse(s) : null; } catch { return null; } }
function $(sel) { return document.querySelector(sel); }
function $$(sel) { return Array.from(document.querySelectorAll(sel)); }

function toast(msg, kind = "") {
  const el = $("#toast");
  el.textContent = msg;
  el.className = "toast " + kind;
  el.classList.remove("hidden");
  clearTimeout(toast._t);
  toast._t = setTimeout(() => el.classList.add("hidden"), 3600);
}

async function api(path, opts = {}) {
  const headers = Object.assign({}, opts.headers || {});
  if (state.token) headers["Authorization"] = "Bearer " + state.token;
  if (opts.body && !(opts.body instanceof FormData)) headers["Content-Type"] = "application/json";

  const res = await fetch(API + path, Object.assign({}, opts, { headers }));
  if (res.status === 204) return null;

  let data = null;
  const ct = res.headers.get("content-type") || "";
  if (ct.includes("application/json")) { data = await res.json().catch(() => null); }

  if (!res.ok) {
    if (res.status === 401 && state.token) { signOut(false); }
    const detail = (data && (data.detail || data.error)) || res.statusText;
    throw new Error(typeof detail === "string" ? detail : "Request failed");
  }
  return data;
}

/* Load an image from an authenticated endpoint into an <img>.
   A plain `img.src = url` cannot carry the Bearer token, so the bytes are
   fetched with the header and handed to the element as an object URL. The
   previous object URL is revoked to avoid leaking memory as the user clicks
   between studies. */
async function authedImage(imgEl, path) {
  if (!imgEl) return;
  try {
    const res = await fetch(API + path, {
      headers: state.token ? { Authorization: "Bearer " + state.token } : {},
    });
    if (!res.ok) throw new Error("Image request failed (" + res.status + ")");
    const blob = await res.blob();
    if (imgEl.dataset.objectUrl) URL.revokeObjectURL(imgEl.dataset.objectUrl);
    const url = URL.createObjectURL(blob);
    imgEl.dataset.objectUrl = url;
    imgEl.src = url;
  } catch (err) {
    imgEl.removeAttribute("src");
    imgEl.alt = "Image unavailable: " + err.message;
  }
}

function show(view) {
  ["auth", "dash", "upload", "study"].forEach((v) => {
    $("#view-" + v).classList.toggle("hidden", v !== view);
  });
  window.scrollTo({ top: 0, behavior: "smooth" });
}

function fmtDate(iso) {
  try { return new Date(iso).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" }); }
  catch { return iso; }
}
function fmtBytes(n) {
  if (n < 1024) return n + " B";
  if (n < 1024 * 1024) return (n / 1024).toFixed(1) + " KB";
  return (n / 1024 / 1024).toFixed(1) + " MB";
}
function esc(s) {
  return String(s == null ? "" : s).replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

/* ---------------- auth ---------------- */

function setSession(token, user) {
  state.token = token; state.user = user;
  localStorage.setItem(TOKEN_KEY, token);
  localStorage.setItem(USER_KEY, JSON.stringify(user));
  renderChrome();
}

function signOut(callApi = true) {
  state.token = ""; state.user = null;
  localStorage.removeItem(TOKEN_KEY);
  localStorage.removeItem(USER_KEY);
  renderChrome();
  show("auth");
  if (callApi) toast("Signed out");
}

function renderChrome() {
  const loggedIn = !!state.token;
  $("#userChip").classList.toggle("hidden", !loggedIn);
  $("#logoutBtn").classList.toggle("hidden", !loggedIn);
  if (loggedIn && state.user) {
    $("#userChip").textContent = state.user.full_name || state.user.email;
  }
}

$$(".tab").forEach((tab) => {
  tab.addEventListener("click", () => {
    $$(".tab").forEach((t) => t.classList.toggle("active", t === tab));
    const which = tab.dataset.tab;
    $("#loginForm").classList.toggle("hidden", which !== "login");
    $("#registerForm").classList.toggle("hidden", which !== "register");
  });
});

$("#loginForm").addEventListener("submit", async (e) => {
  e.preventDefault();
  const f = new FormData(e.target);
  try {
    const data = await api("/api/auth/login", {
      method: "POST",
      body: JSON.stringify({ email: f.get("email"), password: f.get("password") }),
    });
    setSession(data.access_token, data.user);
    toast("Welcome back", "ok");
    await loadStudies();
    show("dash");
  } catch (err) { toast(err.message, "err"); }
});

$("#registerForm").addEventListener("submit", async (e) => {
  e.preventDefault();
  const f = new FormData(e.target);
  try {
    const data = await api("/api/auth/register", {
      method: "POST",
      body: JSON.stringify({
        email: f.get("email"),
        password: f.get("password"),
        full_name: f.get("full_name") || "",
      }),
    });
    setSession(data.access_token, data.user);
    toast("Account created", "ok");
    await loadStudies();
    show("dash");
  } catch (err) { toast(err.message, "err"); }
});

$("#logoutBtn").addEventListener("click", () => signOut());

/* ---------------- studies ---------------- */

async function loadStudies() {
  const data = await api("/api/studies?limit=100");
  state.studies = data.items || [];
  renderStudies();
}

function renderStudies() {
  const grid = $("#studyList");
  const empty = $("#dashEmpty");
  grid.innerHTML = "";
  if (!state.studies.length) { empty.classList.remove("hidden"); return; }
  empty.classList.add("hidden");

  state.studies.forEach((s) => {
    const card = document.createElement("article");
    card.className = "study-card";
    card.innerHTML = `
      <img class="study-thumb" loading="lazy" alt="" />
      <div class="study-body">
        <strong>${esc(s.patient_ref || "Unlabelled study")}</strong>
        <div class="meta">
          <span class="badge">${esc(s.view)}</span>
          <span>${s.width}×${s.height}</span>
          <span>${fmtBytes(s.size_bytes)}</span>
        </div>
        <div class="meta"><span>${fmtDate(s.created_at)}</span></div>
      </div>`;
    card.addEventListener("click", () => openStudy(s.id));
    grid.appendChild(card);
    authedImage(card.querySelector(".study-thumb"), "/api/studies/" + s.id + "/image");
  });
}

$("#newStudyBtn").addEventListener("click", () => {
  state.file = null;
  $("#preview").classList.add("hidden");
  $("#uploadForm").reset();
  $("#uploadSubmit").disabled = true;
  $("#uploadStatus").textContent = "";
  show("upload");
});

$$("[data-back]").forEach((b) => b.addEventListener("click", async () => {
  await loadStudies();
  show("dash");
}));

/* ---------------- upload ---------------- */

const dz = $("#dropzone");
const fileInput = $("#fileInput");

dz.addEventListener("click", () => fileInput.click());
dz.addEventListener("keydown", (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); fileInput.click(); } });
["dragenter", "dragover"].forEach((ev) => dz.addEventListener(ev, (e) => { e.preventDefault(); dz.classList.add("drag"); }));
["dragleave", "drop"].forEach((ev) => dz.addEventListener(ev, (e) => { e.preventDefault(); dz.classList.remove("drag"); }));
dz.addEventListener("drop", (e) => { if (e.dataTransfer.files.length) acceptFile(e.dataTransfer.files[0]); });
fileInput.addEventListener("change", () => { if (fileInput.files.length) acceptFile(fileInput.files[0]); });

function acceptFile(file) {
  const ok = ["image/png", "image/jpeg", "image/webp"].includes(file.type);
  if (!ok) { toast("Only PNG, JPEG or WebP images are accepted", "err"); return; }
  if (file.size > 12 * 1024 * 1024) { toast("File is larger than 12 MB", "err"); return; }
  state.file = file;
  const url = URL.createObjectURL(file);
  const img = $("#preview");
  img.src = url;
  img.classList.remove("hidden");
  $("#uploadSubmit").disabled = false;
  $("#uploadStatus").textContent = file.name + " · " + fmtBytes(file.size);
}

$("#uploadForm").addEventListener("submit", async (e) => {
  e.preventDefault();
  if (!state.file) { toast("Choose an image first", "err"); return; }
  const f = new FormData(e.target);
  const body = new FormData();
  body.append("file", state.file);
  body.append("patient_ref", f.get("patient_ref") || "");
  body.append("view", f.get("view") || "PA");
  body.append("notes", f.get("notes") || "");

  const btn = $("#uploadSubmit");
  btn.disabled = true;
  $("#uploadStatus").textContent = "Uploading…";
  try {
    const study = await api("/api/studies", { method: "POST", body });
    $("#uploadStatus").textContent = "Analysing…";
    await api("/api/analysis/" + study.id, { method: "POST" });
    toast("Study uploaded and analysed", "ok");
    await openStudy(study.id);
  } catch (err) {
    toast(err.message, "err");
    $("#uploadStatus").textContent = "";
    btn.disabled = false;
  }
});

/* ---------------- study detail ---------------- */

async function openStudy(id) {
  try {
    const study = await api("/api/studies/" + id);
    state.current = study;
    state.report = null;
    $("#reportPanel").classList.add("hidden");

    $("#studyTitle").textContent = study.patient_ref || "Unlabelled study";
    $("#studyMeta").textContent =
      `${study.view} view · ${study.width}×${study.height} · ${fmtBytes(study.size_bytes)} · ${fmtDate(study.created_at)}`;
    $("#studyImage").src = "/api/studies/" + id + "/image";
    setViewer("image");

    show("study");
    await loadAnalysis(id);
  } catch (err) { toast(err.message, "err"); }
}

function setViewer(which) {
  $$(".vtab").forEach((t) => t.classList.toggle("active", t.dataset.src === which));
  if (!state.current) return;
  const id = state.current.id;
  authedImage(
    $("#studyImage"),
    which === "overlay" ? "/api/analysis/" + id + "/overlay" : "/api/studies/" + id + "/image"
  );
  $("#viewerNote").textContent = which === "overlay"
    ? "Blue = left lung field, amber = right lung field. These are the regions the engine measured."
    : "The original uploaded radiograph.";
}

$$(".vtab").forEach((t) => t.addEventListener("click", () => setViewer(t.dataset.src)));

async function loadAnalysis(id) {
  try {
    const a = await api("/api/analysis/" + id);
    state.analysis = a;
    renderAnalysis(a);
  } catch (err) {
    state.analysis = null;
    $("#findingsList").innerHTML = "";
    $("#qualityBox").classList.add("hidden");
    $("#analysisEmpty").classList.remove("hidden");
    $("#analysisEmpty").textContent = "No analysis yet — run one to see measurements.";
  }
}

function renderAnalysis(a) {
  $("#analysisEmpty").classList.add("hidden");

  const q = a.quality_score;
  const qbox = $("#qualityBox");
  qbox.classList.remove("hidden");
  qbox.innerHTML = `
    <span class="qpill">Quality <strong>${(q * 100).toFixed(0)}%</strong></span>
    <span class="qpill">Abnormal <strong>${a.abnormal_count}</strong></span>
    <span class="qpill">Confidence <strong>${(a.overall_confidence * 100).toFixed(0)}%</strong></span>
    <span class="qpill">Engine <strong>${esc(a.engine_version)}</strong></span>`;

  const list = $("#findingsList");
  list.innerHTML = "";
  a.findings.forEach((f) => {
    const span = Math.max(f.ref_high - f.ref_low, 0.0001);
    const pct = Math.max(2, Math.min(100, ((f.value - f.ref_low) / span) * 100));
    const el = document.createElement("div");
    el.className = "finding " + f.flag;
    el.innerHTML = `
      <div class="finding-top">
        <strong>${esc(f.label)}</strong>
        <span class="finding-val">${f.value.toFixed(3)} ${esc(f.unit)}</span>
      </div>
      <div class="finding-bar"><span style="width:${pct}%"></span></div>
      <div class="finding-ref">ref ${f.ref_low.toFixed(2)}–${f.ref_high.toFixed(2)} · ${f.flag.toUpperCase()} · confidence ${(f.confidence * 100).toFixed(0)}%</div>
      <div class="finding-note">${esc(f.note)}</div>`;
    list.appendChild(el);
  });
}

$("#reanalyzeBtn").addEventListener("click", async () => {
  if (!state.current) return;
  try {
    toast("Running analysis…");
    const a = await api("/api/analysis/" + state.current.id, { method: "POST" });
    state.analysis = a;
    renderAnalysis(a);
    toast("Analysis complete", "ok");
  } catch (err) { toast(err.message, "err"); }
});

$("#reportBtn").addEventListener("click", async () => {
  if (!state.current) return;
  try {
    const r = await api("/api/reports/" + state.current.id, { method: "POST" });
    state.report = r;
    renderReport(r);
    toast("Report generated", "ok");
  } catch (err) { toast(err.message, "err"); }
});

function renderReport(r) {
  $("#reportTitle").textContent = r.title;
  $("#reportTechnique").textContent = r.technique;
  $("#reportFindings").textContent = r.findings_text;
  $("#reportImpression").textContent = r.impression;
  $("#reportDisclaimer").textContent = r.disclaimer;
  $("#reportPanel").classList.remove("hidden");
  $("#reportPanel").scrollIntoView({ behavior: "smooth", block: "start" });
}

$("#printReport").addEventListener("click", () => window.print());

$("#deleteStudyBtn").addEventListener("click", async () => {
  if (!state.current) return;
  if (!confirm("Delete this study, its analyses and reports? This cannot be undone.")) return;
  try {
    await api("/api/studies/" + state.current.id, { method: "DELETE" });
    toast("Study deleted", "ok");
    await loadStudies();
    show("dash");
  } catch (err) { toast(err.message, "err"); }
});

/* ---------------- boot ---------------- */

(async function boot() {
  renderChrome();
  if (!state.token) { show("auth"); return; }
  try {
    const me = await api("/api/auth/me");
    state.user = me;
    localStorage.setItem(USER_KEY, JSON.stringify(me));
    renderChrome();
    await loadStudies();
    show("dash");
  } catch {
    signOut(false);
    show("auth");
  }
})();
