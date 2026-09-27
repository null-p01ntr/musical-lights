// MusicalLights settings page. Every control saves straight to the backend.
"use strict";

if ("serviceWorker" in navigator) {
  window.addEventListener("load", () => navigator.serviceWorker.register("/static/sw.js"));
}

const $ = (id) => document.getElementById(id);
const BANDS = ["bass", "mid", "treble"];
const DEFAULT_BANDS = { bass: [20, 250], mid: [250, 4000], treble: [4000, 16000] };
let cfg = null;

function toast(msg, bad = false) {
  const t = $("toast");
  t.textContent = msg;
  t.className = `toast show${bad ? " bad" : ""}`;
  clearTimeout(toast.timer);
  toast.timer = setTimeout(() => (t.className = "toast"), 2200);
}

async function call(method, path, body) {
  const r = await fetch(path, {
    method, headers: { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  const data = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(data.error || `HTTP ${r.status}`);
  return data;
}

const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

// ------------------------------------------------------------ light list
function slider(key, label, value, eid) {
  return `<div class="slider"><span>${label}</span>
    <input type="range" min="0" max="100" value="${value}" data-eid="${esc(eid)}" data-key="${key}">
    <output>${value}%</output></div>`;
}

function renderLights() {
  const box = $("light-list");
  if (!cfg.lights.length) { box.innerHTML = '<div class="muted">No lights yet.</div>'; return; }
  box.innerHTML = cfg.lights.map((l) => `
    <div class="cfg-light">
      <div class="row">
        <strong style="word-break:break-all">${esc(l.entity_id)}</strong>
        <span class="tag">${l.kind === "onoff" ? "switch" : "dimmable"}</span>
        <div class="spacer"></div>
        <label class="row muted"><input type="checkbox" data-eid="${esc(l.entity_id)}" data-key="enabled" ${l.enabled ? "checked" : ""}> enabled</label>
      </div>
      <div class="row">
        <select data-eid="${esc(l.entity_id)}" data-key="band">
          ${BANDS.map((b) => `<option value="${b}" ${b === l.band ? "selected" : ""}>${b[0].toUpperCase() + b.slice(1)}</option>`).join("")}
        </select>
        <select data-eid="${esc(l.entity_id)}" data-key="kind" title="How the light is driven">
          <option value="dimmable" ${l.kind === "dimmable" ? "selected" : ""}>Dimmable</option>
          <option value="onoff" ${l.kind === "onoff" ? "selected" : ""}>On/off</option>
        </select>
        <div class="spacer"></div>
        <button class="danger" data-remove="${esc(l.entity_id)}">Remove</button>
      </div>
      ${l.kind === "onoff"
        ? slider("threshold", "Switch threshold", l.threshold, l.entity_id)
        : slider("min_brightness", "Min brightness", l.min_brightness, l.entity_id) +
          slider("max_brightness", "Max brightness", l.max_brightness, l.entity_id)}
    </div>`).join("");
}

$("light-list").addEventListener("input", (e) => {
  if (e.target.type === "range") e.target.nextElementSibling.textContent = `${e.target.value}%`;
});

$("light-list").addEventListener("change", async (e) => {
  const { eid, key } = e.target.dataset;
  if (!eid || !key) return;
  const value = e.target.type === "checkbox" ? e.target.checked
    : e.target.type === "range" ? Number(e.target.value) : e.target.value;
  try {
    const updated = await call("PUT", `/api/lights/${encodeURIComponent(eid)}`, { [key]: value });
    Object.assign(cfg.lights.find((l) => l.entity_id === eid), updated);
    if (key === "kind") renderLights();
    toast(`${eid} saved`);
  } catch (err) { toast(err.message, true); }
});

$("light-list").addEventListener("click", async (e) => {
  const eid = e.target.dataset.remove;
  if (!eid || !confirm(`Remove ${eid} from MusicalLights?`)) return;
  try {
    await call("DELETE", `/api/lights/${encodeURIComponent(eid)}`);
    cfg.lights = cfg.lights.filter((l) => l.entity_id !== eid);
    renderLights();
    toast(`${eid} removed`);
  } catch (err) { toast(err.message, true); }
});

// ------------------------------------------------------------ add light
let lookupTimer = null;
let detectedKind = null;

function updateAddThreshold() {
  const eid = $("add-entity").value.trim().toLowerCase();
  const isSwitch = eid.startsWith("switch.") || detectedKind === "onoff";
  $("add-threshold-row").hidden = !isSwitch;
}

$("add-entity").addEventListener("input", () => {
  detectedKind = null;
  updateAddThreshold();
  $("add-hint").textContent = "";
  clearTimeout(lookupTimer);
  const eid = $("add-entity").value.trim().toLowerCase();
  if (!/^[a-z0-9_]+\.[a-z0-9_]+$/.test(eid)) return;
  lookupTimer = setTimeout(async () => {
    try {
      const info = await call("GET", `/api/entity/${encodeURIComponent(eid)}`);
      if ($("add-entity").value.trim().toLowerCase() !== eid) return;
      detectedKind = info.kind;
      updateAddThreshold();
      if (!info.supported) $("add-hint").textContent = "Only light / switch / input_boolean / fan entities can be driven.";
      else if (info.exists === false) $("add-hint").textContent = "Home Assistant has no entity by that id (you can still add it).";
      else if (info.exists) $("add-hint").textContent = `${info.name || eid} — ${info.state}, ${info.kind === "onoff" ? "on/off only" : "dimmable"}`;
    } catch (_) { /* lookup is a hint, not a gate */ }
  }, 350);
});

$("add-threshold").addEventListener("input", (e) => ($("add-threshold-out").textContent = `${e.target.value}%`));

$("add-btn").addEventListener("click", async () => {
  const entity_id = $("add-entity").value.trim().toLowerCase();
  const body = { entity_id, band: $("add-band").value };
  if (!$("add-threshold-row").hidden) body.threshold = Number($("add-threshold").value);
  try {
    const light = await call("POST", "/api/lights", body);
    cfg.lights.push(light);
    renderLights();
    $("add-entity").value = ""; $("add-hint").textContent = ""; detectedKind = null; updateAddThreshold();
    toast(`${entity_id} added`);
  } catch (err) { toast(err.message, true); }
});

// ------------------------------------------------------------ bands / tuning / HA
function fillBands(bands) {
  for (const b of BANDS) { $(`${b}-lo`).value = bands[b][0]; $(`${b}-hi`).value = bands[b][1]; }
}

$("bands-reset").addEventListener("click", () => fillBands(DEFAULT_BANDS));
$("bands-save").addEventListener("click", async () => {
  const bands = {};
  for (const b of BANDS) bands[b] = [Number($(`${b}-lo`).value), Number($(`${b}-hi`).value)];
  try { cfg = await call("PUT", "/api/settings", { bands }); fillBands(cfg.bands); toast("Bands saved"); }
  catch (err) { toast(err.message, true); }
});

for (const id of ["sensitivity", "smoothing"]) {
  $(id).addEventListener("input", () => ($(`${id}-out`).textContent = $(id).value));
}

$("tuning-save").addEventListener("click", async () => {
  const body = {
    audio: { sensitivity: Number($("sensitivity").value), smoothing: Number($("smoothing").value),
      auto_gain: $("auto_gain").checked },
    output: { max_rate_hz: Number($("max_rate_hz").value), deadband_pct: Number($("deadband_pct").value),
      switch_min_hold_ms: Number($("switch_min_hold_ms").value), watchdog_s: Number($("watchdog_s").value),
      restore_on_stop: $("restore_on_stop").checked },
  };
  try { cfg = await call("PUT", "/api/settings", body); fillTuning(); toast("Saved"); }
  catch (err) { toast(err.message, true); }
});

function fillTuning() {
  $("sensitivity").value = cfg.audio.sensitivity; $("sensitivity-out").textContent = cfg.audio.sensitivity;
  $("smoothing").value = cfg.audio.smoothing; $("smoothing-out").textContent = cfg.audio.smoothing;
  $("auto_gain").checked = cfg.audio.auto_gain;
  for (const k of ["max_rate_hz", "deadband_pct", "switch_min_hold_ms", "watchdog_s"]) $(k).value = cfg.output[k];
  $("restore_on_stop").checked = cfg.output.restore_on_stop;
}

$("ha-save").addEventListener("click", async () => {
  // Fields set by the container environment are locked server-side; don't send them.
  const locked = cfg.ha.locked || [];
  const ha = {};
  if (!locked.includes("url")) ha.url = $("ha-url").value.trim();
  if (!locked.includes("helper")) ha.helper = $("ha-helper").value.trim();
  if (!locked.includes("token") && $("ha-token").value) ha.token = $("ha-token").value.trim();
  try {
    cfg = await call("PUT", "/api/settings", { ha });
    $("ha-token").value = "";
    fillHa();
    toast("Saved — reconnecting");
    setTimeout(refreshHa, 2500);
  } catch (err) { toast(err.message, true); }
});

const ENV_NAMES = { url: "HA_URL", token: "HA_TOKEN", helper: "HA_HELPER" };

function fillHa() {
  const locked = cfg.ha.locked || [];
  $("ha-url").value = cfg.ha.url;
  $("ha-helper").value = cfg.ha.helper;
  $("ha-token").placeholder = cfg.ha.token_set ? "token saved — paste to replace" : "paste a token";
  for (const k of ["url", "token", "helper"]) {
    const el = $(`ha-${k}`);
    el.disabled = locked.includes(k);
    el.title = el.disabled ? `Set by ${ENV_NAMES[k]} in the container environment` : "";
    if (k === "token" && el.disabled) el.placeholder = "set by HA_TOKEN";
  }
  $("ha-save").disabled = locked.length === 3;
}

async function refreshHa() {
  try {
    const h = await call("GET", "/api/health");
    $("ha-pill").className = `pill ${h.ha_connected ? "ok" : "bad"}`;
    $("ha-pill").textContent = h.ha_connected ? "connected" : "offline";
    $("ha-status").textContent = h.ha_status;
  } catch (_) {
    $("ha-pill").className = "pill bad"; $("ha-pill").textContent = "app offline";
  }
}

(async () => {
  cfg = await call("GET", "/api/settings");
  renderLights(); fillBands(cfg.bands); fillTuning(); fillHa(); refreshHa();
  setInterval(refreshHa, 5000);
})();
