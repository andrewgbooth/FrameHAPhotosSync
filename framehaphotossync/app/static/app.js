"use strict";
const $ = (id) => document.getElementById(id);
const FIELDS = ["public_url", "icloud_apple_id", "icloud_password", "tv_host", "time", "frequency",
  "weekday", "day_of_month", "photo_count", "selection", "image_fit", "matte"];
const NUMERIC = ["weekday", "day_of_month", "photo_count"];
const CHECKS = ["schedule_enabled", "replace_previous", "select_first", "enable_art_mode"];
const DEFAULT_MATTES = ["none", "modernthin_black", "modernthin_neutral", "modern_black",
  "shadowbox_black", "shadowbox_polar", "flexible_polar"];
let tvName = "", albumName = "", tvs = [], tvReason = "", pollTimer = null;

async function api(method, path, body) {
  const res = await fetch("api/" + path, {
    method, headers: { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  let data = {};
  try { data = await res.json(); } catch (_) {}
  if (!res.ok) throw new Error(data.error || `Request failed (${res.status})`);
  return data;
}

function say(id, text, kind) {
  const el = $(id);
  el.textContent = text || "";
  el.className = "result" + (kind ? " " + kind : "");
}

async function busy(btn, resultId, fn) {
  btn.disabled = true; say(resultId, "Working…");
  try { await fn(); } catch (e) { say(resultId, e.message, "error"); } finally { btn.disabled = false; }
}

// ---- settings ---------------------------------------------------------
function fillSelect(sel, values, current) {
  sel.replaceChildren();
  const list = values.includes(current) || !current ? values : [current, ...values];
  for (const v of list) {
    const o = document.createElement("option"); o.value = o.textContent = v; sel.append(o);
  }
  if (current) sel.value = current;
}

function applySettings(s) {
  for (const k of FIELDS) if (k !== "matte") $(k).value = s[k] ?? "";
  for (const k of CHECKS) $(k).checked = !!s[k];
  document.querySelector(`input[name=source_type][value=${s.source_type}]`).checked = true;
  fillSelect($("matte"), DEFAULT_MATTES, s.matte);
  tvName = s.tv_name || "";
  albumName = s.private_album_name || "";
  if (s.private_album_id) setAlbums([{ id: s.private_album_id, name: albumName || s.private_album_id }], s.private_album_id);
  else setAlbums([], "");
  syncVisibility(); renderTvSelect();
}

function readSettings() {
  const s = { source_type: document.querySelector("input[name=source_type]:checked").value };
  for (const k of FIELDS) s[k] = NUMERIC.includes(k) ? Number($(k).value) : $(k).value;
  for (const k of CHECKS) s[k] = $(k).checked;
  s.tv_name = tvName;
  const sel = $("private_album_id");
  s.private_album_id = sel.value;
  s.private_album_name = sel.selectedOptions[0] ? sel.selectedOptions[0].textContent : "";
  return s;
}

async function save(quiet) {
  const s = await api("PUT", "settings", readSettings());
  if (!quiet) say("save-result", "Saved ✓", "ok");
  return s;
}

function syncVisibility() {
  const priv = document.querySelector("input[name=source_type]:checked").value === "private";
  $("src-public").classList.toggle("hidden", priv);
  $("src-private").classList.toggle("hidden", !priv);
  const f = $("frequency").value;
  $("weekday-wrap").classList.toggle("hidden", f !== "weekly");
  $("dom-wrap").classList.toggle("hidden", f !== "monthly");
}

// ---- TV ----------------------------------------------------------------
function renderTvSelect() {
  const sel = $("tv-select"); sel.replaceChildren();
  const manual = document.createElement("option");
  manual.value = ""; manual.textContent = tvs.length ? "Enter IP manually…" : "No TVs found in Home Assistant — enter IP";
  sel.append(manual);
  for (const t of tvs) {
    const o = document.createElement("option");
    o.value = t.host; o.textContent = `${t.name} (${t.host})`; sel.append(o);
  }
  sel.value = tvs.some((t) => t.host === $("tv_host").value) ? $("tv_host").value : "";
  $("tv-hint").textContent = tvs.length ? "" : tvReason;
}

$("tv-select").addEventListener("change", (e) => {
  const t = tvs.find((x) => x.host === e.target.value);
  if (t) { $("tv_host").value = t.host; tvName = t.name; } else { tvName = ""; $("tv_host").focus(); }
});
$("tv_host").addEventListener("input", () => { tvName = ""; renderTvSelect(); });

$("test-tv").onclick = (e) => busy(e.target, "tv-result", async () => {
  await save(true);
  const r = await api("POST", "tv/test");
  say("tv-result", `Connected ✓ (Art API ${r.api_version})`, "ok");
});

$("load-mattes").onclick = (e) => busy(e.target, "save-result", async () => {
  await save(true);
  const m = await api("GET", "tv/mattes");
  fillSelect($("matte"), m, $("matte").value);
  say("save-result", `Loaded ${m.length} mattes`, "ok");
});

// ---- iCloud ------------------------------------------------------------
function setAlbums(albums, current) {
  const sel = $("private_album_id"); sel.replaceChildren();
  const blank = document.createElement("option"); blank.value = "";
  blank.textContent = albums.length ? "Select an album…" : "Connect, then load albums"; sel.append(blank);
  for (const a of albums) {
    const o = document.createElement("option"); o.value = a.id;
    o.textContent = a.name + (a.owned === false ? " (shared with me)" : ""); sel.append(o);
  }
  sel.value = current || "";
}

function showAuth(st) {
  $("twofa").classList.toggle("hidden", !st.needs_2fa);
  if (st.needs_2fa) say("icloud-result", "Enter the code sent to your Apple devices.", "");
  else if (st.logged_in) say("icloud-result", "Connected ✓", "ok");
}

$("icloud-connect").onclick = (e) => busy(e.target, "icloud-result", async () => {
  await save(true);
  const st = await api("POST", "icloud/login", {});
  showAuth(st);
  if (st.logged_in) await loadAlbums();
});

$("twofa-submit").onclick = (e) => busy(e.target, "icloud-result", async () => {
  const st = await api("POST", "icloud/2fa", { code: $("twofa-code").value });
  showAuth(st); $("twofa-code").value = "";
  if (st.logged_in) await loadAlbums();
});

async function loadAlbums() {
  const albums = await api("GET", "icloud/albums");
  setAlbums(albums, $("private_album_id").value);
  say("icloud-result", `Found ${albums.length} shared album(s)`, "ok");
}
$("albums-refresh").onclick = (e) => busy(e.target, "icloud-result", async () => { await save(true); await loadAlbums(); });

$("test-public").onclick = (e) => busy(e.target, "public-result", async () => {
  const r = await api("POST", "public/test", { url: $("public_url").value });
  say("public-result", `Found “${r.name || "album"}” with ${r.count} photos ✓`, "ok");
});

// ---- status / sync -----------------------------------------------------
const fmt = (iso) => iso ? new Date(iso).toLocaleString([], { dateStyle: "medium", timeStyle: "short" }) : "–";
let lastUploadedKey = "";

async function refreshStatus() {
  try {
    const st = await api("GET", "status");
    $("last-run").textContent = fmt(st.last_run_at);
    $("next-run").textContent = st.next_run ? fmt(st.next_run) : "Not scheduled";
    $("last-message").textContent = st.last_message || "";
    const kind = st.running ? "running" : st.last_status || "";
    $("status-dot").className = "dot " + kind;
    $("status-text").textContent = st.running ? "Syncing…" : ({ ok: "Last sync OK", error: "Last sync failed" }[st.last_status] || "Idle");
    $("sync-now").disabled = st.running;
    const ul = $("log"); ul.replaceChildren();
    for (const l of [...st.log].reverse()) {
      const li = document.createElement("li"); li.className = l.level;
      const t = document.createElement("time"); t.textContent = new Date(l.t).toLocaleTimeString();
      li.append(t, document.createTextNode(l.msg)); ul.append(li);
    }
    const key = st.uploaded.join(",");
    if (key !== lastUploadedKey) { lastUploadedKey = key; markOnTv(new Set(st.uploaded)); }
    schedulePoll(st.running ? 2000 : 15000);
  } catch (e) { $("status-text").textContent = e.message; schedulePoll(15000); }
}
function schedulePoll(ms) { clearTimeout(pollTimer); pollTimer = setTimeout(refreshStatus, ms); }

$("sync-now").onclick = async (e) => {
  e.target.disabled = true;
  try { await save(true); await api("POST", "sync"); } catch (err) { $("last-message").textContent = err.message; }
  refreshStatus();
};

// ---- preview -----------------------------------------------------------
function markOnTv(ids) {
  for (const el of document.querySelectorAll(".photo")) {
    const has = ids.has(el.dataset.id), b = el.querySelector(".badge");
    if (has && !b) { const x = document.createElement("span"); x.className = "badge"; x.textContent = "On TV"; el.append(x); }
    if (!has && b) b.remove();
  }
}

async function loadPreview(refresh) {
  const info = $("preview-info"), grid = $("preview");
  info.textContent = "Loading…"; grid.replaceChildren();
  try {
    const r = await api("GET", "photos" + (refresh ? "?refresh=1" : ""));
    info.textContent = `${r.total} photo(s) in the album — showing the latest ${r.photos.length}.`;
    for (const p of r.photos) {
      const d = document.createElement("div"); d.className = "photo"; d.dataset.id = p.id;
      const img = document.createElement("img"); img.loading = "lazy"; img.alt = p.caption || "";
      img.src = "api/thumb?id=" + encodeURIComponent(p.id);
      d.append(img);
      if (p.on_tv) { const b = document.createElement("span"); b.className = "badge"; b.textContent = "On TV"; d.append(b); }
      if (p.taken) { const t = document.createElement("span"); t.className = "date"; t.textContent = new Date(p.taken).toLocaleDateString(); d.append(t); }
      grid.append(d);
    }
  } catch (e) { info.textContent = e.message; }
}
$("preview-refresh").onclick = () => loadPreview(true);

// ---- init --------------------------------------------------------------
$("save").onclick = (e) => busy(e.target, "save-result", async () => { await save(false); loadPreview(true); refreshStatus(); });
for (const el of document.querySelectorAll("input[name=source_type], #frequency")) el.addEventListener("change", syncVisibility);

(async function init() {
  try { const d = await api("GET", "ha/tvs"); tvs = d.tvs; tvReason = d.reason; } catch (e) { tvReason = e.message; }
  try {
    applySettings(await api("GET", "settings"));
    const s = readSettings();
    if (s.source_type === "private" && s.icloud_apple_id) {
      const st = await api("GET", "icloud/status").catch(() => ({}));
      if (st.needs_2fa) showAuth(st);
    }
  } catch (e) { say("save-result", e.message, "error"); }
  refreshStatus(); loadPreview(false);
})();
