"use strict";
// Browser point reviewer. Shares the data model, calibration and keymap with the
// matplotlib reviewer (review_points.py); edits are POSTed back and saved to edits.json.
// You edit in pixel space; the 'r' key converts T/mole_fraction via the calibration.

const BASE_PX = 0.5, SHIFT_PX = 5.0, CLICK_PX = 12.0, HIST_MAX = 60;

const S = {            // app state
  plot: null, width: 0, height: 0, calib: null, palette: {}, order: [], series: {},
  si: 0, sel: null, dirty: false, img: null, mode: "select",
  view: { scale: 1, offX: 0, offY: 0 },   // offX/offY = image px at canvas (0,0)
  history: [],                            // snapshots of S.series for undo
};

const cv = document.getElementById("cv");
const ctx = cv.getContext("2d");
const $ = (id) => document.getElementById(id);

// ---- coordinate transforms -------------------------------------------------
const cssW = () => cv.clientWidth, cssH = () => cv.clientHeight;
const i2cx = (px) => (px - S.view.offX) * S.view.scale;
const i2cy = (py) => (py - S.view.offY) * S.view.scale;
const c2ix = (cx) => S.view.offX + cx / S.view.scale;
const c2iy = (cy) => S.view.offY + cy / S.view.scale;

function pxToData(px, py) {
  const c = S.calib;
  return [c.x_k0 + (px - c.x_p0) * c.x_KperPx,
          Math.pow(10, c.y_log0 - (py - c.y0px) / c.y_pxPerDecade)];
}
function dataToPx(T, mf) {
  const c = S.calib;
  return [c.x_p0 + (T - c.x_k0) / c.x_KperPx,
          c.y0px + (c.y_log0 - Math.log10(mf)) * c.y_pxPerDecade];
}

// WPD step: zoom = full width / view width (in image px); nudge = base / zoom.
function zoom() { return S.width / (cssW() / S.view.scale); }
function stepPx(shift) { return (shift ? SHIFT_PX : BASE_PX) / zoom(); }

// ---- series / selection helpers --------------------------------------------
const curName = () => S.order[S.si];
const curPts = () => S.series[curName()] || [];
function ordered(liveOnly) {
  let p = curPts().slice();
  if (liveOnly) p = p.filter((q) => !q.deleted);
  return p.sort((a, b) => a.px - b.px || a.py - b.py);
}
function markOverride(p) { if (p.source === "auto") p.source = "override"; }

// ---- undo ------------------------------------------------------------------
function snapshot() {
  S.history.push(JSON.stringify(S.series));
  if (S.history.length > HIST_MAX) S.history.shift();
}
function undo() {
  const snap = S.history.pop();
  if (snap === undefined) { flash("nothing to undo"); return; }
  S.series = JSON.parse(snap);
  // keep selection if that id still exists in the same series
  S.sel = S.sel ? curPts().find((p) => p.id === S.sel.id) || null : null;
  S.dirty = true;
}

// ---- mutations (each snapshots first) --------------------------------------
function move(dx, dy) {
  if (!S.sel) return;
  snapshot();
  S.sel.px += dx; S.sel.py += dy; markOverride(S.sel); S.dirty = true;
  ensureVisible(S.sel);
}
function removeOrToggle(p) {
  // manual points are removed outright (a mistaken add just disappears); auto points
  // are flagged deleted so they can be restored.
  snapshot();
  if (p.id.startsWith("auto_")) {
    p.deleted = !p.deleted;
  } else {
    const arr = curPts(); const i = arr.indexOf(p);
    if (i >= 0) arr.splice(i, 1);
    if (S.sel === p) S.sel = null;
  }
  S.dirty = true;
}
function restoreAuto() {
  const p = S.sel;
  if (!p || !p.id.startsWith("auto_")) { flash("restore: select an auto point"); return; }
  snapshot();
  p.px = p.orig_px; p.py = p.orig_py; p.source = "auto"; p.note = ""; p.deleted = false;
  S.dirty = true;
}
function setFromData() {
  if (!S.sel) { flash("set T,mf: select a point first"); return; }
  const [T0, mf0] = pxToData(S.sel.px, S.sel.py);
  const t = prompt("T_K:", T0.toFixed(1)); if (t === null) return;
  const m = prompt("mole_fraction:", mf0.toExponential(4)); if (m === null) return;
  const T = parseFloat(t), mf = parseFloat(m);
  if (!isFinite(T) || !isFinite(mf) || mf <= 0) { alert("invalid number"); return; }
  snapshot();
  [S.sel.px, S.sel.py] = dataToPx(T, mf); markOverride(S.sel); S.dirty = true;
  ensureVisible(S.sel);
}
function addManual(px, py) {
  snapshot();
  const n = curPts().filter((p) => p.id.startsWith("manual_")).length + 1;
  const id = `manual_${curName()}_${String(n).padStart(3, "0")}`;
  const p = { id, px, py, source: "manual", deleted: false, note: "",
              orig_px: null, orig_py: null };
  curPts().push(p); S.dirty = true; return p;
}
function selectOffset(d) {
  const p = ordered(false);
  if (!p.length) { S.sel = null; return; }
  let i = p.indexOf(S.sel);
  if (i < 0) i = d > 0 ? -1 : 0;
  S.sel = p[(i + d + p.length) % p.length];
  ensureVisible(S.sel);
}
function changeSeries(d) {
  S.si = (S.si + d + S.order.length) % S.order.length;
  S.sel = null; $("series").value = curName();
}
function nearestInSeries(px, py) {
  const tol = CLICK_PX / S.view.scale;          // CLICK_PX screen px, in image px
  let best = null, bd = tol * tol;
  for (const q of ordered(false)) {
    const d = (q.px - px) ** 2 + (q.py - py) ** 2;
    if (d < bd) { best = q; bd = d; }
  }
  return best;
}

// ---- view ------------------------------------------------------------------
function fitView() {
  const s = Math.min(cssW() / S.width, cssH() / S.height) * 0.96;
  S.view.scale = s;
  S.view.offX = -(cssW() / s - S.width) / 2;
  S.view.offY = -(cssH() / s - S.height) / 2;
}
function zoomAt(cx, cy, factor) {
  const ix = c2ix(cx), iy = c2iy(cy);
  S.view.scale *= factor;
  S.view.offX = ix - cx / S.view.scale;
  S.view.offY = iy - cy / S.view.scale;
}
function centerOn(px, py) {
  S.view.offX = px - (cssW() / S.view.scale) / 2;
  S.view.offY = py - (cssH() / S.view.scale) / 2;
}
// recenter only if the point is outside the central 70% of the viewport, so Tab never
// loses the selection off-screen but small hops don't make the view jump around.
function ensureVisible(p) {
  if (!p) return;
  const x = i2cx(p.px), y = i2cy(p.py);
  const mx = cssW() * 0.15, my = cssH() * 0.15;
  if (x < mx || x > cssW() - mx || y < my || y > cssH() - my) centerOn(p.px, p.py);
}

// ---- rendering -------------------------------------------------------------
function render() {
  const dpr = window.devicePixelRatio || 1;
  if (cv.width !== cssW() * dpr || cv.height !== cssH() * dpr) {
    cv.width = cssW() * dpr; cv.height = cssH() * dpr;
  }
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.clearRect(0, 0, cssW(), cssH());
  if (!S.img) return;

  ctx.imageSmoothingEnabled = S.view.scale < 3;
  ctx.drawImage(S.img, i2cx(0), i2cy(0), S.width * S.view.scale, S.height * S.view.scale);

  for (const name of S.order) {
    const cur = name === curName();
    const col = S.palette[name] || "#000";
    for (const p of S.series[name]) {
      const x = i2cx(p.px), y = i2cy(p.py);
      if (x < -20 || y < -20 || x > cssW() + 20 || y > cssH() + 20) continue;
      ctx.globalAlpha = cur ? 1 : 0.32;
      if (p.deleted) {
        if (!cur) continue;
        ctx.strokeStyle = "#888"; ctx.lineWidth = 1.4; ctx.globalAlpha = 0.5;
        ctx.beginPath(); ctx.moveTo(x - 5, y - 5); ctx.lineTo(x + 5, y + 5);
        ctx.moveTo(x + 5, y - 5); ctx.lineTo(x - 5, y + 5); ctx.stroke();
        continue;
      }
      const r = cur ? 4.5 : 3;
      ctx.fillStyle = col;
      ctx.beginPath(); ctx.arc(x, y, r, 0, 7); ctx.fill();
      if (p.source !== "auto") {
        ctx.strokeStyle = "#22e0e0"; ctx.lineWidth = 2;
        ctx.beginPath(); ctx.arc(x, y, r + 2.5, 0, 7); ctx.stroke();
      }
    }
  }
  ctx.globalAlpha = 1;
  drawSelection();
  hud();
}

function drawSelection() {
  if (!S.sel) return;
  const x = i2cx(S.sel.px), y = i2cy(S.sel.py);
  ctx.strokeStyle = "#ff3b3b"; ctx.lineWidth = 2;
  ctx.beginPath(); ctx.arc(x, y, 11, 0, 7); ctx.stroke();
  ctx.beginPath(); ctx.arc(x, y, 5, 0, 7); ctx.stroke();          // inner ring
  ctx.beginPath();                                                // crosshair ticks
  for (const [dx, dy] of [[0, -1], [0, 1], [-1, 0], [1, 0]]) {
    ctx.moveTo(x + dx * 8, y + dy * 8); ctx.lineTo(x + dx * 15, y + dy * 15);
  }
  ctx.stroke();
  const live = ordered(true);
  const idx = live.indexOf(S.sel);
  if (idx >= 0) {
    ctx.fillStyle = "#ff3b3b"; ctx.font = "bold 12px ui-monospace, monospace";
    ctx.fillText(`${idx + 1}/${live.length}`, x + 16, y - 12);
  }
}

let flashMsg = "", flashAt = 0;
function flash(m) { flashMsg = m; flashAt = Date.now(); hud(); }

function hud() {
  const live = ordered(true);
  let sel = "—";
  if (S.sel) {
    const [T, mf] = pxToData(S.sel.px, S.sel.py);
    const i = live.indexOf(S.sel);
    sel = `${S.sel.deleted ? "DEL " : ""}${S.sel.id} [${S.sel.source}]` +
          (i >= 0 ? `  point ${i + 1}/${live.length}` : "") +
          `\nT=${T.toFixed(1)}K  mf=${mf.toExponential(4)}`;
  }
  const fl = (flashMsg && Date.now() - flashAt < 2500) ? `\n» ${flashMsg}` : "";
  $("hud").textContent =
    `mode: ${S.mode.toUpperCase()}   ${S.plot}   species ${S.si + 1}/${S.order.length}: ` +
    `${curName()} (${live.length} live)\nzoom x${zoom().toFixed(1)}   ` +
    `step ${stepPx(false).toFixed(3)}px\n${sel}${fl}`;
  $("status").textContent = `${S.order.length} species`;
  $("dirty").textContent = S.dirty ? "● unsaved" : "";
}

function setMode(m) {
  S.mode = m;
  const b = $("modeBtn");
  b.textContent = m.toUpperCase(); b.className = m;
  cv.className = m;
  render();
}

// ---- data ------------------------------------------------------------------
async function loadState(name) {
  const st = await (await fetch(`/api/state?plot=${encodeURIComponent(name)}`)).json();
  if (st.error) { alert(st.error); return; }
  Object.assign(S, st, { si: 0, sel: null, dirty: false, history: [] });
  const ssel = $("series");
  ssel.innerHTML = "";
  for (const s of S.order) {
    const o = document.createElement("option"); o.value = o.textContent = s; ssel.add(o);
  }
  const img = new Image();
  img.onload = () => { S.img = img; fitView(); render(); };
  img.src = `/img?plot=${encodeURIComponent(name)}`;
}
async function save() {
  const r = await (await fetch("/api/save", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ plot: S.plot, series: S.series, export: true }),
  })).json();
  if (r.error) { alert(r.error); return; }
  S.dirty = false;
  const n = r.csv ? Object.values(r.csv).reduce((a, b) => a + b, 0) : 0;
  flash(r.csv ? `saved + exported ${n} pts across ${Object.keys(r.csv).length} CSVs`
              : "saved " + r.path);
}

// ---- events ----------------------------------------------------------------
function onKey(e) {
  const tag = (e.target.tagName || "").toUpperCase();
  if (tag === "SELECT" || tag === "INPUT") return;
  const k = e.key;
  if ((e.ctrlKey || e.metaKey) && (k === "z" || k === "Z")) { undo(); e.preventDefault(); return render(); }
  let handled = true;
  switch (k) {
    case "ArrowLeft":  move(-stepPx(e.shiftKey), 0); break;
    case "ArrowRight": move(stepPx(e.shiftKey), 0); break;
    case "ArrowUp":    move(0, -stepPx(e.shiftKey)); break;
    case "ArrowDown":  move(0, stepPx(e.shiftKey)); break;
    case "Tab":        selectOffset(e.shiftKey ? -1 : 1); break;
    case ",":          changeSeries(-1); break;
    case ".":          changeSeries(1); break;
    case "a":          setMode(S.mode === "add" ? "select" : "add"); return;
    case "Escape":     setMode("select"); S.sel = null; break;
    case "d": case "Delete": case "Backspace": if (S.sel) removeOrToggle(S.sel); break;
    case "z":          undo(); break;
    case "u":          restoreAuto(); break;
    case "r":          setFromData(); break;
    case "s":          save(); break;
    default: handled = false;
  }
  if (handled) { e.preventDefault(); render(); }
}

let drag = null;
function onDown(e) {
  if (e.button !== 0) return;                   // left only; right -> contextmenu
  drag = { x: e.clientX, y: e.clientY, moved: 0, ox: S.view.offX, oy: S.view.offY };
}
function onMove(e) {
  if (!drag) return;
  const dx = e.clientX - drag.x, dy = e.clientY - drag.y;
  drag.moved = Math.max(drag.moved, Math.abs(dx) + Math.abs(dy));
  S.view.offX = drag.ox - dx / S.view.scale;
  S.view.offY = drag.oy - dy / S.view.scale;
  render();
}
function onUp(e) {
  if (drag && drag.moved < 4) {                 // a click, not a pan
    const r = cv.getBoundingClientRect();
    const px = c2ix(e.clientX - r.left), py = c2iy(e.clientY - r.top);
    const hit = nearestInSeries(px, py);
    if (S.mode === "add") {
      S.sel = hit || addManual(px, py);         // in ADD mode empty space places a point
    } else {
      S.sel = hit;                              // SELECT mode never creates points
      if (!hit) flash("nothing here — switch to ADD (a) to place a point");
    }
    render();
  }
  drag = null;
}
function onContext(e) {                          // right-click deletes the nearest point
  e.preventDefault();
  const r = cv.getBoundingClientRect();
  const hit = nearestInSeries(c2ix(e.clientX - r.left), c2iy(e.clientY - r.top));
  if (hit) { removeOrToggle(hit); render(); } else flash("right-click on a point to delete");
}
function onWheel(e) {
  e.preventDefault();
  const r = cv.getBoundingClientRect();
  zoomAt(e.clientX - r.left, e.clientY - r.top, e.deltaY < 0 ? 1.15 : 1 / 1.15);
  render();
}

async function init() {
  const plots = await (await fetch("/api/plots")).json();
  const psel = $("plot");
  for (const p of plots) {
    const o = document.createElement("option"); o.value = o.textContent = p; psel.add(o);
  }
  const want = new URLSearchParams(location.search).get("plot");
  psel.value = plots.includes(want) ? want : plots[0];
  psel.onchange = () => loadState(psel.value);
  $("series").onchange = (e) => { S.si = S.order.indexOf(e.target.value); S.sel = null;
                                  e.target.blur(); render(); };
  $("prevS").onclick = () => { changeSeries(-1); render(); };
  $("nextS").onclick = () => { changeSeries(1); render(); };
  $("modeBtn").onclick = () => setMode(S.mode === "add" ? "select" : "add");
  $("rBtn").onclick = () => { setFromData(); render(); };
  $("undoBtn").onclick = () => { undo(); render(); };
  $("saveBtn").onclick = () => save();
  window.addEventListener("keydown", onKey);
  cv.addEventListener("mousedown", onDown);
  window.addEventListener("mousemove", onMove);
  window.addEventListener("mouseup", onUp);
  cv.addEventListener("contextmenu", onContext);
  cv.addEventListener("wheel", onWheel, { passive: false });
  window.addEventListener("resize", () => render());
  await loadState(psel.value);
}
init();
