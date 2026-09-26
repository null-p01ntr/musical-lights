// MusicalLights live page: mic capture, 3-band analysis, WebSocket to the backend.
// All audio maths happens here; the backend only ever sees three numbers (0..1).
"use strict";

const BANDS = ["bass", "mid", "treble"];
const SEND_EVERY_MS = 50;          // 20 level updates/s to the backend
const PEAK_DECAY_DB_S = 4;         // auto-gain: how fast a loud peak is forgotten
const PEAK_MIN_DB = -75;           // auto-gain never amplifies below this (silence stays dark)
const FIXED_PEAK_DB = -30;         // reference when auto-gain is off
const RANGE_DB = 30;               // peak..peak-30dB maps to 1..0 at sensitivity 1
const GATE_DB = -100;              // anything quieter is treated as silence

const $ = (id) => document.getElementById(id);
const power = $("power");

let settings = null;
let ws = null;
let server = null;                 // last state pushed by the backend
let audio = null;                  // {ctx, stream, analyser, freq, time}
let levels = { bass: 0, mid: 0, treble: 0 };
let peaks = { bass: PEAK_MIN_DB, mid: PEAK_MIN_DB, treble: PEAK_MIN_DB };
let lastFrame = performance.now();
let lastSend = 0;
let wakeLock = null;
let pending = false;               // start/stop request in flight
let wasSource = false;             // this page has been the session's audio source
let lostControl = false;           // ...and another device has since claimed it

// ------------------------------------------------------------ backend link
function connect() {
  const proto = location.protocol === "https:" ? "wss" : "ws";
  ws = new WebSocket(`${proto}://${location.host}/ws`);
  ws.onmessage = (e) => { server = JSON.parse(e.data); render(); };
  ws.onclose = () => { server = null; render(); setTimeout(connect, 1500); };
}

async function loadSettings() {
  try {
    const r = await fetch("/api/settings");
    if (r.ok) settings = await r.json();
  } catch (_) { /* keep the last good copy */ }
}

async function api(path) {
  const r = await fetch(path, { method: "POST" });
  const body = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(body.error || `HTTP ${r.status}`);
  return body;
}

// ------------------------------------------------------------ audio
async function startMic() {
  const stream = await navigator.mediaDevices.getUserMedia({
    // Voice processing would flatten exactly the dynamics we want to follow.
    audio: { echoCancellation: false, noiseSuppression: false, autoGainControl: false },
  });
  const ctx = new (window.AudioContext || window.webkitAudioContext)();
  await ctx.resume();
  const analyser = ctx.createAnalyser();
  analyser.fftSize = 4096;
  analyser.smoothingTimeConstant = 0;
  ctx.createMediaStreamSource(stream).connect(analyser);
  audio = {
    ctx, stream, analyser,
    freq: new Float32Array(analyser.frequencyBinCount),
    time: new Float32Array(analyser.fftSize),
  };
  peaks = { bass: PEAK_MIN_DB, mid: PEAK_MIN_DB, treble: PEAK_MIN_DB };
  try { wakeLock = await navigator.wakeLock?.request("screen"); } catch (_) { wakeLock = null; }
}

function stopMic() {
  if (audio) {
    audio.stream.getTracks().forEach((t) => t.stop());
    audio.ctx.close();
    audio = null;
  }
  levels = { bass: 0, mid: 0, treble: 0 };
  wakeLock?.release?.().catch(() => {});
  wakeLock = null;
}

// Mean power across the band's FFT bins, back in dB.
function bandDb(lo, hi) {
  const binHz = audio.ctx.sampleRate / audio.analyser.fftSize;
  const a = Math.max(1, Math.floor(lo / binHz));
  const b = Math.min(audio.freq.length - 1, Math.ceil(hi / binHz));
  let sum = 0, n = 0;
  for (let i = a; i <= b; i++) { sum += Math.pow(10, audio.freq[i] / 10); n++; }
  return n ? 10 * Math.log10(sum / n + 1e-20) : -200;
}

function analyse(dt) {
  audio.analyser.getFloatFrequencyData(audio.freq);
  const a = settings?.audio || { auto_gain: true, sensitivity: 1, smoothing: 0.6 };
  const range = RANGE_DB * a.sensitivity;
  const keep = Math.pow(a.smoothing, dt * 60);    // frame-rate independent release
  for (const band of BANDS) {
    const [lo, hi] = settings?.bands?.[band] || [20, 250];
    const db = bandDb(lo, hi);
    let peak = FIXED_PEAK_DB;
    if (a.auto_gain) {
      peaks[band] = Math.max(db, peaks[band] - PEAK_DECAY_DB_S * dt, PEAK_MIN_DB);
      peak = peaks[band];
    }
    const raw = db < GATE_DB ? 0 : Math.min(1, Math.max(0, 1 - (peak - db) / range));
    // Instant attack, smoothed release: hits land on the beat, fades don't flicker.
    levels[band] = raw >= levels[band] ? raw : levels[band] * keep + raw * (1 - keep);
  }
}

// ------------------------------------------------------------ drawing
const canvas = $("wave");
const g = canvas.getContext("2d");

function drawWave() {
  const dpr = window.devicePixelRatio || 1;
  const w = canvas.clientWidth, h = canvas.clientHeight;
  if (canvas.width !== w * dpr) { canvas.width = w * dpr; canvas.height = h * dpr; }
  g.setTransform(dpr, 0, 0, dpr, 0, 0);
  g.clearRect(0, 0, w, h);
  g.lineWidth = 2;
  g.strokeStyle = audio ? "#ffb547" : "#3a3f50";
  g.beginPath();
  if (audio) {
    audio.analyser.getFloatTimeDomainData(audio.time);
    const step = audio.time.length / w;
    for (let x = 0; x < w; x++) {
      const v = audio.time[Math.floor(x * step)];
      const y = h / 2 - v * h * 0.45 * 2;
      x ? g.lineTo(x, y) : g.moveTo(x, y);
    }
  } else {
    g.moveTo(0, h / 2); g.lineTo(w, h / 2);
  }
  g.stroke();
}

function frame(now) {
  const dt = Math.min(0.1, (now - lastFrame) / 1000);
  lastFrame = now;
  if (audio) {
    analyse(dt);
    if (now - lastSend >= SEND_EVERY_MS && ws?.readyState === WebSocket.OPEN && server?.active) {
      ws.send(JSON.stringify({ type: "levels", ...levels }));
      lastSend = now;
    }
  }
  drawWave();
  const shown = audio ? levels : (server?.active ? server.levels : null) || {};
  for (const b of BANDS) {
    const v = Math.round((shown[b] || 0) * 100);
    $(`m-${b}`).style.width = `${v}%`;
    $(`lv-${b}`).textContent = v;
  }
  requestAnimationFrame(frame);
}

// ------------------------------------------------------------ UI state
function render() {
  const pill = $("ha-pill");
  if (!server) {
    pill.className = "pill bad"; pill.textContent = "app offline";
  } else {
    pill.className = `pill ${server.ha.connected ? "ok" : "bad"}`;
    pill.textContent = server.ha.connected ? "HA connected" : "HA offline";
    pill.title = server.ha.status;
  }
  const active = !!server?.active;
  if (!pending) power.checked = active;
  power.disabled = pending || !server || server.busy;
  $("power-label").textContent = active ? "Listening" : "Off";
  const sess = server?.session || {};
  if (active && audio && sess.you_are_source) wasSource = true;
  // Another tab or device claimed the session: hand the mic back instead of competing.
  // (No source at all is just a reconnect gap: our next levels make us the source again.)
  if (active && audio && wasSource && !sess.you_are_source && sess.source_connected && !pending) {
    stopMic();
    lostControl = true;
  }

  let detail = "Toggle to start listening";
  if (active && audio) {
    detail = "Driving the lights from this device's mic";
  } else if (active) {
    // Levels are fresh => someone really is sending. Stale => an orphaned session that
    // only the watchdog will end (a closed tab, or a page reload that dropped the mic).
    const sending = sess.source_connected && sess.idle_s != null && sess.idle_s < 2;
    const left = Math.max(0, Math.ceil((sess.watchdog_s ?? 0) - (sess.idle_s ?? 0)));
    detail = lostControl ? "Another device took control"
      : sending ? "Running from another device"
      : `No device is sending audio — stops in ${left}s`;
  } else if (server?.last_stop_reason) {
    detail = `Stopped: ${server.last_stop_reason}`;
  }
  $("power-detail").textContent = detail;
  $("take-control").hidden = !(active && !audio);
  $("take-control").disabled = pending || !!server?.busy;
  // Opening Settings in this tab would reload the page and drop the mic.
  $("nav-settings").target = audio ? "_blank" : "";
  if (!active) lostControl = false;

  // The session ended under us (watchdog, helper off in HA, another device).
  if (!active && audio && !pending) stopMic();

  const box = $("lights");
  const lights = (server?.lights || []).filter((l) => l.enabled);
  if (!lights.length) { box.innerHTML = '<div class="muted">No lights configured — add some in Settings.</div>'; return; }
  box.innerHTML = lights.map((l) => {
    const pct = l.brightness == null ? null : l.brightness;
    const label = pct == null ? "—" : l.kind === "onoff" ? (l.on ? "ON" : "OFF") : `${pct}%`;
    return `<div class="light ${l.band}">
      <div class="glow" style="opacity:${pct == null ? 0 : (pct / 100) * 0.55}"></div>
      <div class="eid">${l.entity_id}</div>
      <div><span class="tag ${l.band}">${l.band}</span><span class="tag">${l.kind === "onoff" ? "switch" : "dimmable"}</span></div>
      <div class="pct">${label}</div>
    </div>`;
  }).join("");
}

power.addEventListener("change", async () => {
  $("error").textContent = "";
  pending = true; render();
  try {
    if (power.checked) {
      await loadSettings();
      if (!navigator.mediaDevices?.getUserMedia) throw new Error("This browser blocks the mic here (needs HTTPS).");
      await startMic();
      wasSource = false; lostControl = false;
      try { await api("/api/start"); } catch (e) { stopMic(); throw e; }
    } else {
      await api("/api/stop");
      stopMic();
    }
  } catch (e) {
    $("error").textContent = e.message || String(e);
    power.checked = false;
  } finally {
    pending = false; render();
  }
});

// Take over a running session: open this device's mic and make it the only source.
// The session keeps going (no restart, no re-snapshot of the lights).
$("take-control").addEventListener("click", async () => {
  $("error").textContent = "";
  pending = true; render();
  try {
    await loadSettings();
    if (!navigator.mediaDevices?.getUserMedia) throw new Error("This browser blocks the mic here (needs HTTPS).");
    await startMic();
    if (ws?.readyState !== WebSocket.OPEN) { stopMic(); throw new Error("Not connected to the app"); }
    wasSource = false; lostControl = false;
    ws.send(JSON.stringify({ type: "claim" }));
  } catch (e) {
    $("error").textContent = e.message || String(e);
  } finally {
    pending = false; render();
  }
});

document.addEventListener("visibilitychange", async () => {
  if (document.visibilityState === "visible" && audio && !wakeLock) {
    try { wakeLock = await navigator.wakeLock?.request("screen"); } catch (_) {}
  }
});
setInterval(() => { if (audio) loadSettings(); }, 5000);   // pick up band edits live

loadSettings();
connect();
requestAnimationFrame(frame);
