"""MusicalLights -- drive Home Assistant lights from live audio band levels.

The browser owns the audio: it captures the mic, splits it into bass/mid/treble with
the Web Audio FFT and streams normalised levels (0..1) here over a WebSocket. This
process owns everything that touches the house:

  * one persistent HA WebSocket connection (service calls are fire-and-forget),
  * the level -> brightness / on-off mapping per light,
  * pacing -- a per-light rate cap and a deadband, because Tuya cloud and WiZ bulbs
    drop commands well before a naive 30 fps stream, and a relay must not chatter,
  * the session: flips the HA helper on start, snapshots the lights, restores them
    and flips the helper off on stop -- including when the browser just vanishes
    (watchdog) or someone turns the helper off from inside HA.

HA side is deliberately one helper and nothing else; the helper is what the house's
own automations check so they keep their hands off while a session runs.
"""

import asyncio
import copy
import json
import logging
import os
import re
import ssl
import time
from pathlib import Path

from aiohttp import ClientSession, ClientTimeout, WSMsgType, web

log = logging.getLogger("musical-lights")

DATA_DIR = Path(os.environ.get("DATA_DIR", "/data"))
SETTINGS_FILE = DATA_DIR / "settings.json"
STATIC_DIR = Path(__file__).parent / "static"

BANDS = ("bass", "mid", "treble")
ENTITY_RE = re.compile(r"^[a-z0-9_]+\.[a-z0-9_]+$")
ONOFF_DOMAINS = {"switch", "input_boolean", "fan", "siren"}
SUPPORTED_DOMAINS = ONOFF_DOMAINS | {"light"}

TICK_S = 0.05              # engine loop, 20 Hz
PUSH_EVERY_TICKS = 2       # state pushed to browsers at 10 Hz
KEEPALIVE_S = 3.0          # resend even inside the deadband, so a light another actor
                           # touched is pulled back within a few seconds
SWITCH_HYSTERESIS = 10     # points below the threshold before a switch drops out

DEFAULTS = {
    "ha": {
        "url": "http://homeassistant.local:8123",
        "token": "",
        "helper": "input_boolean.musicallights",
    },
    "bands": {"bass": [20, 250], "mid": [250, 4000], "treble": [4000, 16000]},
    "audio": {"auto_gain": True, "sensitivity": 1.0, "smoothing": 0.6},
    "output": {
        "max_rate_hz": 4.0,
        "deadband_pct": 4,
        "switch_min_hold_ms": 1000,
        "watchdog_s": 6,
        "restore_on_stop": True,
    },
    "lights": [],
}

# Environment. The HA_* variables override whatever is saved and lock that field in the UI
# (a value that silently reverted to the environment on restart would be worse).
# ML_LIGHTS only seeds the light list on first run; after that the Settings page owns it.
ENV_HA = {"url": "HA_URL", "token": "HA_TOKEN", "helper": "HA_HELPER"}


def new_light(entity_id, band="bass", kind="dimmable", threshold=80):
    return {"entity_id": entity_id, "band": band, "kind": kind, "min_brightness": 5,
            "max_brightness": 100, "threshold": threshold, "enabled": True}


def parse_lights_env(value):
    """ML_LIGHTS="light.a:bass,switch.b:treble:80" -> light dicts. Bad entries are skipped."""
    out = []
    for item in (value or "").split(","):
        parts = [p.strip() for p in item.strip().split(":")]
        if not parts[0]:
            continue
        eid = parts[0].lower()
        band = parts[1].lower() if len(parts) > 1 and parts[1] else "bass"
        if not ENTITY_RE.match(eid) or band not in BANDS:
            log.warning("ML_LIGHTS: skipping %r", item)
            continue
        light = new_light(eid, band, kind_from_state(eid, None))
        if len(parts) > 2 and parts[2].isdigit():
            light["threshold"] = min(100, int(parts[2]))
            light["kind"] = "onoff"     # a threshold only means anything for on/off
        out.append(light)
    return out

LIGHT_FIELDS = {
    "band": str, "kind": str, "min_brightness": int, "max_brightness": int,
    "threshold": int, "enabled": bool,
}


class BadRequest(Exception):
    pass


# ---------------------------------------------------------------- settings

def _merge(base, over):
    out = copy.deepcopy(base)
    for k, v in (over or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _merge(out[k], v)
        else:
            out[k] = v
    return out


class Settings:
    def __init__(self, path: Path, environ=None):
        env = os.environ if environ is None else environ
        self.path = path
        self.data = copy.deepcopy(DEFAULTS)
        if path.exists():
            try:
                self.data = _merge(DEFAULTS, json.loads(path.read_text()))
            except (OSError, ValueError) as e:
                log.error("settings unreadable, using defaults: %s", e)
        else:
            self.data["lights"] = parse_lights_env(env.get("ML_LIGHTS"))
        self.env = {k: env[v].strip() for k, v in ENV_HA.items() if env.get(v, "").strip()}
        self.save()

    def ha(self, key):
        """Effective HA setting: environment first, then what was saved from the UI."""
        return self.env.get(key, self.data["ha"][key])

    def save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.data, indent=2))
        os.chmod(tmp, 0o600)
        tmp.replace(self.path)

    def public(self):
        """Everything except the token -- that never leaves this process."""
        d = copy.deepcopy(self.data)
        d["ha"].pop("token")
        d["ha"].update(url=self.ha("url"), helper=self.ha("helper"),
                       token_set=bool(self.ha("token")), locked=sorted(self.env))
        return d

    def light(self, entity_id):
        return next((l for l in self.data["lights"] if l["entity_id"] == entity_id), None)


def validate_light_patch(patch):
    out = {}
    for k, v in patch.items():
        if k not in LIGHT_FIELDS:
            continue
        typ = LIGHT_FIELDS[k]
        try:
            v = typ(v) if typ is not bool else bool(v)
        except (TypeError, ValueError):
            raise BadRequest(f"{k}: bad value")
        if k == "band" and v not in BANDS:
            raise BadRequest(f"band must be one of {BANDS}")
        if k == "kind" and v not in ("dimmable", "onoff"):
            raise BadRequest("kind must be dimmable or onoff")
        if k in ("min_brightness", "max_brightness", "threshold") and not 0 <= v <= 100:
            raise BadRequest(f"{k} must be 0-100")
        out[k] = v
    return out


def validate_bands(bands):
    out = {}
    for b in BANDS:
        try:
            lo, hi = (int(x) for x in bands[b])
        except (KeyError, TypeError, ValueError):
            raise BadRequest(f"bands.{b} must be [low_hz, high_hz]")
        if not (10 <= lo < hi <= 22000):
            raise BadRequest(f"bands.{b}: need 10 <= low < high <= 22000")
        out[b] = [lo, hi]
    return out


def kind_from_state(entity_id, state):
    domain = entity_id.split(".", 1)[0]
    if domain in ONOFF_DOMAINS:
        return "onoff"
    modes = (state or {}).get("attributes", {}).get("supported_color_modes") or []
    if domain == "light" and modes and set(modes) <= {"onoff"}:
        return "onoff"
    return "dimmable"


# ---------------------------------------------------------------- HA client

class HAUnavailable(Exception):
    pass


class HAClient:
    """One persistent HA WebSocket. Reconnects forever; `reload()` after settings change."""

    def __init__(self, settings: Settings):
        self.settings = settings
        self.ws = None
        self.http = None
        self.connected = False
        self.status = "not configured"
        self.errors = 0
        self.last_error = None
        self._id = 0
        self._pending = {}
        self._send_lock = asyncio.Lock()
        self._reload = asyncio.Event()
        self._sub_id = None
        self._auth_failed = False
        self.on_helper = None       # async callback(new_state)
        self.on_connect = None      # async callback()

    @property
    def base(self):
        return self.settings.ha("url").rstrip("/")

    @property
    def token(self):
        return self.settings.ha("token")

    def reload(self):
        self._reload.set()
        if self.ws is not None and not self.ws.closed:
            asyncio.ensure_future(self.ws.close())

    async def run(self):
        self.http = ClientSession(timeout=ClientTimeout(total=10))
        while True:
            self._reload.clear()
            self._auth_failed = False
            if not self.token:
                self.status = "not configured"
                await self._wait_reload(3600)
                continue
            try:
                await self._session()
            except asyncio.CancelledError:
                raise
            except Exception as e:  # noqa: BLE001 -- reconnect on anything
                if not self._auth_failed:
                    self.status = f"disconnected: {e.__class__.__name__}: {e}"
                log.warning("HA connection: %s", self.status)
            finally:
                self.connected = False
                self.ws = None
                for f in self._pending.values():
                    if not f.done():
                        f.set_exception(HAUnavailable("connection lost"))
                self._pending.clear()
            # A rejected token will not fix itself; back off until settings change.
            await self._wait_reload(300 if self._auth_failed else 5)

    async def _wait_reload(self, timeout):
        try:
            await asyncio.wait_for(self._reload.wait(), timeout)
        except asyncio.TimeoutError:
            pass

    async def _session(self):
        url = re.sub(r"^http", "ws", self.base) + "/api/websocket"
        async with self.http.ws_connect(url, heartbeat=30) as ws:
            self.ws = ws
            msg = await ws.receive_json(timeout=10)
            if msg.get("type") != "auth_required":
                raise HAUnavailable(f"unexpected greeting {msg.get('type')}")
            await ws.send_json({"type": "auth", "access_token": self.token})
            msg = await ws.receive_json(timeout=10)
            if msg.get("type") != "auth_ok":
                self.status = "auth rejected -- check the token"
                self._auth_failed = True
                raise HAUnavailable(self.status)
            self.connected = True
            self.status = f"connected (HA {msg.get('ha_version', '?')})"
            log.info("HA %s", self.status)
            reader = asyncio.ensure_future(self._reader(ws))
            try:
                self._sub_id = await self._subscribe_helper()
                if self.on_connect:
                    await self.on_connect()
                await reader
            finally:
                reader.cancel()

    async def _subscribe_helper(self):
        helper = self.settings.ha("helper")
        mid = self._next_id()
        fut = asyncio.get_running_loop().create_future()
        self._pending[mid] = fut
        await self._send({"id": mid, "type": "subscribe_trigger",
                          "trigger": {"platform": "state", "entity_id": helper}})
        await asyncio.wait_for(fut, 10)
        return mid

    async def _reader(self, ws):
        async for msg in ws:
            if msg.type != WSMsgType.TEXT:
                if msg.type in (WSMsgType.CLOSED, WSMsgType.ERROR):
                    break
                continue
            data = json.loads(msg.data)
            mid = data.get("id")
            if data.get("type") == "result":
                fut = self._pending.pop(mid, None)
                if fut and not fut.done():
                    fut.set_result(data)
                elif not data.get("success"):
                    self.errors += 1
                    self.last_error = (data.get("error") or {}).get("message")
                    log.warning("HA call %s failed: %s", mid, self.last_error)
            elif data.get("type") == "event" and mid == self._sub_id and self.on_helper:
                to = (((data.get("event") or {}).get("variables") or {})
                      .get("trigger", {}).get("to_state") or {})
                asyncio.ensure_future(self.on_helper(to.get("state")))

    def _next_id(self):
        self._id += 1
        return self._id

    async def _send(self, payload):
        async with self._send_lock:
            await self.ws.send_json(payload)

    async def call(self, domain, service, entity_id, data=None, wait=False):
        if not self.connected or self.ws is None:
            raise HAUnavailable(self.status)
        mid = self._next_id()
        fut = None
        if wait:
            fut = asyncio.get_running_loop().create_future()
            self._pending[mid] = fut
        await self._send({"id": mid, "type": "call_service", "domain": domain,
                          "service": service, "service_data": data or {},
                          "target": {"entity_id": entity_id}})
        if wait:
            res = await asyncio.wait_for(fut, 10)
            if not res.get("success"):
                raise HAUnavailable((res.get("error") or {}).get("message", "call failed"))
            return res

    async def get_state(self, entity_id):
        """REST read of one entity. None if HA says it does not exist."""
        if not self.token:
            raise HAUnavailable("not configured")
        async with self.http.get(f"{self.base}/api/states/{entity_id}",
                                 headers={"Authorization": f"Bearer {self.token}"}) as r:
            if r.status == 404:
                return None
            if r.status == 401:
                raise HAUnavailable("auth rejected -- check the token")
            r.raise_for_status()
            return await r.json()


# ---------------------------------------------------------------- engine

def service_for(entity_id, on):
    domain = entity_id.split(".", 1)[0]
    if domain not in ("light", "switch", "input_boolean", "fan", "siren"):
        domain = "homeassistant"
    return domain, "turn_on" if on else "turn_off"


class Engine:
    def __init__(self, settings: Settings, ha: HAClient):
        self.settings = settings
        self.ha = ha
        self.active = False
        self.busy = False           # start/stop in progress
        self.levels = {b: 0.0 for b in BANDS}
        self.last_levels_at = 0.0
        self.snapshot = {}          # entity_id -> HA state dict at session start
        self.out = {}               # entity_id -> runtime output state
        self.clients = set()
        self.last_stop_reason = None
        ha.on_helper = self._helper_changed
        ha.on_connect = self._ha_connected

    # -- session ---------------------------------------------------------
    async def start(self):
        if self.active or self.busy:
            return
        self.busy = True
        try:
            helper = self.settings.ha("helper")
            await self.ha.call(*service_for(helper, True), helper, wait=True)
            # Let the house react to the helper first (an automation releasing its
            # lamp, etc.) so the snapshot is of the lights as the house left them.
            await asyncio.sleep(1.0)
            self.snapshot = {}
            for l in self.settings.data["lights"]:
                await self._snap(l["entity_id"])
            self.out = {}
            self.levels = {b: 0.0 for b in BANDS}
            self.last_levels_at = time.monotonic()
            self.active = True
            self.last_stop_reason = None
            log.info("session started, %d lights", len(self.snapshot))
        finally:
            self.busy = False

    async def stop(self, reason="stopped", touch_helper=True):
        if not self.active or self.busy:
            return
        self.busy = True
        self.active = False
        self.last_stop_reason = reason
        log.info("session stopping: %s", reason)
        try:
            if self.settings.data["output"]["restore_on_stop"]:
                for eid in list(self.snapshot):
                    await self._restore(eid)
            if touch_helper:
                helper = self.settings.ha("helper")
                try:
                    await self.ha.call(*service_for(helper, False), helper)
                except HAUnavailable as e:
                    log.warning("could not turn helper off: %s", e)
        finally:
            self.snapshot = {}
            self.out = {}
            self.busy = False

    async def _snap(self, entity_id):
        try:
            st = await self.ha.get_state(entity_id)
        except Exception as e:  # noqa: BLE001
            log.warning("snapshot %s failed: %s", entity_id, e)
            st = None
        if st:
            self.snapshot[entity_id] = st

    async def _restore(self, entity_id):
        st = self.snapshot.pop(entity_id, None)
        if not st or st.get("state") not in ("on", "off"):
            return
        on = st["state"] == "on"
        data = {}
        bri = (st.get("attributes") or {}).get("brightness")
        if on and entity_id.startswith("light.") and bri is not None:
            data["brightness"] = bri
        try:
            await self.ha.call(*service_for(entity_id, on), entity_id, data)
        except HAUnavailable as e:
            log.warning("restore %s failed: %s", entity_id, e)

    async def lights_changed(self, removed=None, added=None):
        """Keep the session's snapshot in step with light add/remove mid-session."""
        if not self.active:
            return
        if removed:
            await self._restore(removed)
            self.out.pop(removed, None)
        if added:
            await self._snap(added)

    async def _helper_changed(self, state):
        if state == "off" and self.active and not self.busy:
            await self.stop("helper turned off in Home Assistant", touch_helper=False)

    async def _ha_connected(self):
        # A helper left on with no session behind it (container restart mid-session)
        # would keep the house's automations locked out indefinitely.
        if self.active:
            return
        helper = self.settings.ha("helper")
        try:
            st = await self.ha.get_state(helper)
            if st and st.get("state") == "on":
                log.info("helper was left on with no session; turning it off")
                await self.ha.call(*service_for(helper, False), helper)
        except Exception as e:  # noqa: BLE001
            log.warning("helper check failed: %s", e)

    # -- mapping ---------------------------------------------------------
    def set_levels(self, levels):
        if not self.active:
            return
        for b in BANDS:
            try:
                self.levels[b] = min(1.0, max(0.0, float(levels.get(b, 0.0))))
            except (TypeError, ValueError):
                pass
        self.last_levels_at = time.monotonic()

    @staticmethod
    def target_for(light, level):
        """Level 0..1 -> (on, brightness_pct) for one light. Pure; unit-tested."""
        if light["kind"] == "onoff":
            return level * 100 >= light["threshold"], None
        lo, hi = light["min_brightness"], light["max_brightness"]
        if hi < lo:
            lo, hi = hi, lo
        pct = round(lo + level * (hi - lo))
        return pct > 0, pct

    def decide(self, light, now):
        """What to send for this light right now, or None. Mutates self.out."""
        cfg = self.settings.data["output"]
        eid = light["entity_id"]
        o = self.out.setdefault(eid, {"sent_on": None, "sent_pct": None, "sent_at": 0.0,
                                      "on": False, "pct": 0, "changed_at": 0.0})
        level = self.levels[light["band"]]
        since = now - o["sent_at"]
        if light["kind"] == "onoff":
            want = o["on"]
            if level * 100 >= light["threshold"]:
                want = True
            elif level * 100 < light["threshold"] - SWITCH_HYSTERESIS:
                want = False
            held = (now - o["changed_at"]) * 1000
            if want != o["on"] and (o["sent_on"] is None or held >= cfg["switch_min_hold_ms"]):
                o["on"], o["changed_at"] = want, now
            o["pct"] = 100 if o["on"] else 0
            if o["sent_on"] != o["on"] or since >= KEEPALIVE_S * 2:
                o["sent_on"], o["sent_at"] = o["on"], now
                return service_for(eid, o["on"]) + (eid, {})
            return None
        on, pct = self.target_for(light, level)
        o["on"], o["pct"] = on, pct
        if since < 1.0 / max(0.5, float(cfg["max_rate_hz"])):
            return None
        moved = o["sent_pct"] is None or abs(pct - o["sent_pct"]) >= cfg["deadband_pct"]
        if not moved and since < KEEPALIVE_S:
            return None
        o["sent_pct"], o["sent_on"], o["sent_at"] = pct, on, now
        if not on:
            return service_for(eid, False) + (eid, {})
        return ("light", "turn_on", eid, {"brightness_pct": pct})

    async def run(self):
        tick = 0
        while True:
            await asyncio.sleep(TICK_S)
            tick += 1
            now = time.monotonic()
            if self.active and not self.busy:
                wd = self.settings.data["output"]["watchdog_s"]
                if now - self.last_levels_at > wd:
                    asyncio.ensure_future(self.stop(f"no audio for {wd}s (browser closed?)"))
                elif self.ha.connected:
                    for light in self.settings.data["lights"]:
                        if not light["enabled"]:
                            continue
                        cmd = self.decide(light, now)
                        if cmd:
                            try:
                                await self.ha.call(*cmd)
                            except HAUnavailable:
                                pass
            if tick % PUSH_EVERY_TICKS == 0 and self.clients:
                await self.broadcast()

    # -- browser side ----------------------------------------------------
    def status(self):
        lights = []
        for l in self.settings.data["lights"]:
            o = self.out.get(l["entity_id"], {})
            lights.append({"entity_id": l["entity_id"], "band": l["band"],
                           "kind": l["kind"], "enabled": l["enabled"],
                           "on": bool(o.get("on")) if self.active else None,
                           "brightness": o.get("pct", 0) if self.active else None})
        return {"type": "state", "active": self.active, "busy": self.busy,
                "levels": self.levels, "lights": lights,
                "ha": {"connected": self.ha.connected, "status": self.ha.status,
                       "errors": self.ha.errors, "last_error": self.ha.last_error},
                "last_stop_reason": self.last_stop_reason}

    async def broadcast(self):
        msg = json.dumps(self.status())
        for ws in list(self.clients):
            try:
                await ws.send_str(msg)
            except (ConnectionError, RuntimeError):
                self.clients.discard(ws)


# ---------------------------------------------------------------- HTTP API

def json_error(status, msg):
    return web.json_response({"error": msg}, status=status)


async def read_json(request):
    try:
        body = await request.json()
    except ValueError:
        raise BadRequest("body must be JSON")
    if not isinstance(body, dict):
        raise BadRequest("body must be a JSON object")
    return body


@web.middleware
async def errors_mw(request, handler):
    try:
        return await handler(request)
    except BadRequest as e:
        return json_error(400, str(e))
    except HAUnavailable as e:
        return json_error(503, f"Home Assistant: {e}")


def make_app(settings=None, ha=None, engine=None):
    settings = settings or Settings(SETTINGS_FILE)
    ha = ha or HAClient(settings)
    engine = engine or Engine(settings, ha)
    routes = web.RouteTableDef()

    @routes.get("/")
    async def index(_):
        return web.FileResponse(STATIC_DIR / "index.html")

    @routes.get("/settings")
    async def settings_page(_):
        return web.FileResponse(STATIC_DIR / "settings.html")

    @routes.get("/api/health")
    async def health(_):
        return web.json_response({"ok": True, "active": engine.active,
                                  "ha_connected": ha.connected, "ha_status": ha.status})

    @routes.get("/api/status")
    async def status(_):
        return web.json_response(engine.status())

    @routes.post("/api/start")
    async def start(_):
        await engine.start()
        return web.json_response(engine.status())

    @routes.post("/api/stop")
    async def stop(_):
        await engine.stop("stopped from the app")
        return web.json_response(engine.status())

    @routes.get("/api/settings")
    async def get_settings(_):
        return web.json_response(settings.public())

    @routes.put("/api/settings")
    async def put_settings(request):
        body = await read_json(request)
        d = settings.data
        if "bands" in body:
            d["bands"] = validate_bands(body["bands"])
        for section, fields in (("audio", {"auto_gain": bool, "sensitivity": float,
                                           "smoothing": float}),
                                ("output", {"max_rate_hz": float, "deadband_pct": int,
                                            "switch_min_hold_ms": int, "watchdog_s": int,
                                            "restore_on_stop": bool})):
            for k, v in (body.get(section) or {}).items():
                if k in fields:
                    try:
                        d[section][k] = fields[k](v)
                    except (TypeError, ValueError):
                        raise BadRequest(f"{section}.{k}: bad value")
        a, o = d["audio"], d["output"]
        a["sensitivity"] = min(5.0, max(0.1, a["sensitivity"]))
        a["smoothing"] = min(0.95, max(0.0, a["smoothing"]))
        o["max_rate_hz"] = min(20.0, max(0.5, o["max_rate_hz"]))
        o["deadband_pct"] = min(50, max(0, o["deadband_pct"]))
        o["switch_min_hold_ms"] = min(10000, max(0, o["switch_min_hold_ms"]))
        o["watchdog_s"] = min(120, max(2, o["watchdog_s"]))
        reconnect = False
        for k in ("url", "token", "helper"):
            v = (body.get("ha") or {}).get(k)
            if v is None or (k == "token" and v == ""):
                continue            # empty token field = keep the stored one
            v = str(v).strip()
            if k == "helper" and not ENTITY_RE.match(v):
                raise BadRequest("helper must be an entity id")
            if k == "url" and not re.match(r"^https?://", v):
                raise BadRequest("url must start with http:// or https://")
            if k in settings.env:
                raise BadRequest(f"ha.{k} is set by the {ENV_HA[k]} environment variable")
            if d["ha"][k] != v:
                if k == "helper" and engine.active:
                    raise BadRequest("stop the session before changing the helper")
                d["ha"][k] = v
                reconnect = True
        settings.save()
        if reconnect:
            ha.reload()
        return web.json_response(settings.public())

    @routes.get("/api/entity/{entity_id}")
    async def entity(request):
        eid = request.match_info["entity_id"]
        if not ENTITY_RE.match(eid):
            raise BadRequest("not an entity id")
        domain = eid.split(".", 1)[0]
        guess = kind_from_state(eid, None)
        if not ha.token:
            return web.json_response({"entity_id": eid, "exists": None, "kind": guess,
                                      "supported": domain in SUPPORTED_DOMAINS})
        st = await ha.get_state(eid)
        return web.json_response({
            "entity_id": eid, "exists": st is not None,
            "state": st and st.get("state"),
            "name": st and st.get("attributes", {}).get("friendly_name"),
            "kind": kind_from_state(eid, st), "supported": domain in SUPPORTED_DOMAINS})

    @routes.post("/api/lights")
    async def add_light(request):
        body = await read_json(request)
        eid = str(body.get("entity_id", "")).strip().lower()
        if not ENTITY_RE.match(eid):
            raise BadRequest("entity_id must look like light.some_light")
        if eid.split(".", 1)[0] not in SUPPORTED_DOMAINS:
            raise BadRequest(f"unsupported domain; use one of {sorted(SUPPORTED_DOMAINS)}")
        if settings.light(eid):
            raise BadRequest(f"{eid} is already configured")
        st = None
        if ha.token:
            try:
                st = await ha.get_state(eid)
            except Exception:  # noqa: BLE001 -- adding offline is allowed
                st = None
        light = new_light(eid, kind=kind_from_state(eid, st))
        light.update(validate_light_patch(body))
        settings.data["lights"].append(light)
        settings.save()
        await engine.lights_changed(added=eid)
        return web.json_response(light, status=201)

    @routes.put("/api/lights/{entity_id}")
    async def update_light(request):
        eid = request.match_info["entity_id"]
        light = settings.light(eid)
        if not light:
            return json_error(404, f"{eid} not configured")
        was_enabled = light["enabled"]
        light.update(validate_light_patch(await read_json(request)))
        settings.save()
        if was_enabled and not light["enabled"]:
            await engine.lights_changed(removed=eid)
        elif light["enabled"] and not was_enabled:
            await engine.lights_changed(added=eid)
        engine.out.pop(eid, None)
        return web.json_response(light)

    @routes.delete("/api/lights/{entity_id}")
    async def delete_light(request):
        eid = request.match_info["entity_id"]
        light = settings.light(eid)
        if not light:
            return json_error(404, f"{eid} not configured")
        settings.data["lights"].remove(light)
        settings.save()
        await engine.lights_changed(removed=eid)
        return web.json_response({"deleted": eid})

    @routes.get("/ws")
    async def ws_handler(request):
        ws = web.WebSocketResponse(heartbeat=20)
        await ws.prepare(request)
        engine.clients.add(ws)
        await ws.send_str(json.dumps(engine.status()))
        try:
            async for msg in ws:
                if msg.type != WSMsgType.TEXT:
                    continue
                try:
                    data = json.loads(msg.data)
                except ValueError:
                    continue
                if data.get("type") == "levels":
                    engine.set_levels(data)
        finally:
            engine.clients.discard(ws)
        return ws

    app = web.Application(middlewares=[errors_mw])
    app.add_routes(routes)
    app.router.add_static("/static/", STATIC_DIR)
    app["settings"], app["ha"], app["engine"] = settings, ha, engine

    async def background(app_):
        tasks = [asyncio.ensure_future(ha.run()), asyncio.ensure_future(engine.run())]
        yield
        if engine.active:
            await engine.stop("server shutting down")
        for t in tasks:
            t.cancel()
        if ha.http:
            await ha.http.close()

    app.cleanup_ctx.append(background)
    return app


def main():
    logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"),
                        format="%(asctime)s %(levelname)s %(message)s")
    ctx = None
    cert, key = os.environ.get("TLS_CERT"), os.environ.get("TLS_KEY")
    if cert and key:
        ctx = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
        ctx.load_cert_chain(cert, key)
    web.run_app(make_app(), port=int(os.environ.get("PORT", "8443")), ssl_context=ctx,
                access_log=None)


if __name__ == "__main__":
    main()
