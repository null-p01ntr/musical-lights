"""MusicalLights tests. No real Home Assistant: a fake HA speaks the same WebSocket and
REST shapes the app uses, and records every service call so we can assert on them.

Run inside the image:  docker compose run --rm --entrypoint python musical-lights -m unittest -v
"""

import asyncio
import json
import sys
import tempfile
import time
import unittest
from pathlib import Path

from aiohttp import WSMsgType, web
from aiohttp.test_utils import TestClient, TestServer

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import app as ml  # noqa: E402

TOKEN = "good-token"
LIGHTS = "light.tv_ambient_light:bass,light.single_colored_light:mid,light.cinema_light:treble:80"
HELPER = "input_boolean.musicallights"


class FakeHA:
    def __init__(self):
        self.states = {
            HELPER: {"entity_id": HELPER, "state": "off", "attributes": {}},
            "light.tv_ambient_light": {"entity_id": "light.tv_ambient_light", "state": "off",
                                       "attributes": {"supported_color_modes": ["hs", "white"]}},
            "light.single_colored_light": {"entity_id": "light.single_colored_light", "state": "on",
                                           "attributes": {"brightness": 200,
                                                          "supported_color_modes": ["color_temp", "rgbw"]}},
            "light.cinema_light": {"entity_id": "light.cinema_light", "state": "off",
                                   "attributes": {"supported_color_modes": ["onoff"]}},
            "switch.plug": {"entity_id": "switch.plug", "state": "off", "attributes": {}},
        }
        self.calls = []
        self.subs = []          # (ws, id)

    def app(self):
        a = web.Application()
        a.router.add_get("/api/websocket", self.ws)
        a.router.add_get("/api/states/{eid}", self.state)
        return a

    async def state(self, request):
        if request.headers.get("Authorization") != f"Bearer {TOKEN}":
            return web.json_response({}, status=401)
        st = self.states.get(request.match_info["eid"])
        return web.json_response(st) if st else web.json_response({}, status=404)

    async def set_state(self, eid, state, **attrs):
        self.states[eid]["state"] = state
        self.states[eid]["attributes"].update(attrs)
        if eid == HELPER:
            for ws, sid in self.subs:
                if ws.closed:
                    continue
                await ws.send_json({"id": sid, "type": "event", "event": {"variables": {
                    "trigger": {"to_state": {"entity_id": eid, "state": state}}}}})

    async def ws(self, request):
        ws = web.WebSocketResponse()
        await ws.prepare(request)
        await ws.send_json({"type": "auth_required"})
        auth = await ws.receive_json()
        if auth.get("access_token") != TOKEN:
            await ws.send_json({"type": "auth_invalid"})
            await ws.close()
            return ws
        await ws.send_json({"type": "auth_ok", "ha_version": "fake"})
        async for msg in ws:
            if msg.type != WSMsgType.TEXT:
                continue
            m = json.loads(msg.data)
            if m["type"] == "subscribe_trigger":
                self.subs.append((ws, m["id"]))
                await ws.send_json({"id": m["id"], "type": "result", "success": True})
            elif m["type"] == "call_service":
                eid = m["target"]["entity_id"]
                self.calls.append((m["domain"], m["service"], eid, m["service_data"]))
                if eid not in self.states:
                    await ws.send_json({"id": m["id"], "type": "result", "success": False,
                                        "error": {"message": f"{eid} not found"}})
                    continue
                attrs = {}
                if "brightness_pct" in m["service_data"]:
                    attrs["brightness"] = round(m["service_data"]["brightness_pct"] * 2.55)
                if "brightness" in m["service_data"]:
                    attrs["brightness"] = m["service_data"]["brightness"]
                await self.set_state(eid, "on" if m["service"] == "turn_on" else "off", **attrs)
                await ws.send_json({"id": m["id"], "type": "result", "success": True})
        return ws


def light(**kw):
    base = {"entity_id": "light.x", "band": "bass", "kind": "dimmable", "min_brightness": 5,
            "max_brightness": 100, "threshold": 80, "enabled": True}
    base.update(kw)
    return base


class MappingTests(unittest.TestCase):
    def test_dimmable_scales_between_min_and_max(self):
        self.assertEqual(ml.Engine.target_for(light(), 0.0), (True, 5))
        self.assertEqual(ml.Engine.target_for(light(), 1.0), (True, 100))
        self.assertEqual(ml.Engine.target_for(light(min_brightness=20, max_brightness=60), 0.5), (True, 40))

    def test_dimmable_zero_min_turns_off(self):
        self.assertEqual(ml.Engine.target_for(light(min_brightness=0), 0.0), (False, 0))

    def test_onoff_threshold(self):
        sw = light(kind="onoff", threshold=80)
        self.assertEqual(ml.Engine.target_for(sw, 0.79)[0], False)
        self.assertEqual(ml.Engine.target_for(sw, 0.80)[0], True)

    def test_kind_detection(self):
        self.assertEqual(ml.kind_from_state("switch.a", None), "onoff")
        self.assertEqual(ml.kind_from_state("light.a", {"attributes": {"supported_color_modes": ["onoff"]}}), "onoff")
        self.assertEqual(ml.kind_from_state("light.a", {"attributes": {"supported_color_modes": ["hs"]}}), "dimmable")
        self.assertEqual(ml.kind_from_state("light.a", None), "dimmable")


class EnvTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "s.json"

    def tearDown(self):
        self.tmp.cleanup()

    def test_ml_lights_parsing(self):
        lights = ml.parse_lights_env(" light.a:mid , switch.b:treble:70, light.c, bad id:bass, light.d:loud")
        self.assertEqual([(l["entity_id"], l["band"], l["kind"], l["threshold"]) for l in lights], [
            ("light.a", "mid", "dimmable", 80),
            ("switch.b", "treble", "onoff", 70),
            ("light.c", "bass", "dimmable", 80),
        ])

    def test_ml_lights_seeds_first_run_only(self):
        s = ml.Settings(self.path, environ={"ML_LIGHTS": "light.a:bass"})
        self.assertEqual([l["entity_id"] for l in s.data["lights"]], ["light.a"])
        s.data["lights"] = []
        s.save()
        s = ml.Settings(self.path, environ={"ML_LIGHTS": "light.a:bass"})
        self.assertEqual(s.data["lights"], [])          # the UI's list wins after first run

    def test_env_overrides_lock_and_never_persist_the_token(self):
        s = ml.Settings(self.path, environ={"HA_URL": "http://ha:8123", "HA_TOKEN": "env-secret"})
        self.assertEqual((s.ha("url"), s.ha("token")), ("http://ha:8123", "env-secret"))
        self.assertEqual(s.ha("helper"), "input_boolean.musicallights")
        pub = s.public()
        self.assertEqual(pub["ha"]["locked"], ["token", "url"])
        self.assertTrue(pub["ha"]["token_set"])
        self.assertNotIn("env-secret", json.dumps(pub))
        self.assertNotIn("env-secret", self.path.read_text())

    def test_defaults_are_house_neutral(self):
        s = ml.Settings(self.path, environ={})
        self.assertEqual(s.data["lights"], [])
        self.assertFalse(s.public()["ha"]["token_set"])


class DecideTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.settings = ml.Settings(Path(self.tmp.name) / "s.json", environ={})
        self.engine = ml.Engine(self.settings, ml.HAClient(self.settings))
        self.engine.active = True

    def tearDown(self):
        self.tmp.cleanup()

    def test_rate_cap_and_deadband(self):
        lt = light(entity_id="light.a")
        self.settings.data["output"].update(max_rate_hz=4, deadband_pct=4)
        self.engine.levels["bass"] = 0.5
        self.assertIsNotNone(self.engine.decide(lt, 100.0))          # first send
        self.engine.levels["bass"] = 0.9
        self.assertIsNone(self.engine.decide(lt, 100.1))              # < 250 ms later
        self.assertEqual(self.engine.decide(lt, 100.3)[3], {"brightness_pct": 90})
        self.engine.levels["bass"] = 0.91
        self.assertIsNone(self.engine.decide(lt, 100.6))              # inside deadband
        self.assertIsNotNone(self.engine.decide(lt, 100.3 + ml.KEEPALIVE_S))  # keepalive

    def test_switch_hysteresis_and_min_hold(self):
        sw = light(entity_id="switch.p", kind="onoff", threshold=80)
        self.settings.data["output"]["switch_min_hold_ms"] = 1000
        e = self.engine
        e.levels["bass"] = 0.5
        self.assertEqual(e.decide(sw, 10.0)[:2], ("switch", "turn_off"))
        e.levels["bass"] = 0.85
        self.assertEqual(e.decide(sw, 11.5)[:2], ("switch", "turn_on"))
        e.levels["bass"] = 0.75                                        # in hysteresis band
        self.assertIsNone(e.decide(sw, 13.0))
        e.levels["bass"] = 0.2
        self.assertIsNone(e.decide(sw, 11.9))                          # held < 1 s
        self.assertEqual(e.decide(sw, 12.6)[:2], ("switch", "turn_off"))


class E2ETests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.fake = FakeHA()
        self.ha_server = TestServer(self.fake.app())
        await self.ha_server.start_server()
        # Explicit environment: the container's own HA_* must never point tests at a real HA.
        self.settings = ml.Settings(Path(self.tmp.name) / "s.json", environ={"ML_LIGHTS": LIGHTS})
        self.settings.data["ha"]["url"] = str(self.ha_server.make_url("")).rstrip("/")
        self.settings.data["ha"]["token"] = TOKEN
        self.settings.data["output"]["watchdog_s"] = 2
        self.client = TestClient(TestServer(ml.make_app(self.settings)))
        await self.client.start_server()
        self.engine = self.client.server.app["engine"]
        await self.wait_for(lambda: self.client.server.app["ha"].connected)

    async def asyncTearDown(self):
        await self.client.close()
        await self.ha_server.close()
        self.tmp.cleanup()

    async def wait_for(self, cond, timeout=5.0):
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            if cond():
                return
            await asyncio.sleep(0.05)
        self.fail("condition not met in time")

    async def test_health_and_settings_hide_token(self):
        r = await self.client.get("/api/health")
        self.assertEqual((await r.json())["ha_connected"], True)
        s = await (await self.client.get("/api/settings")).json()
        self.assertNotIn("token", s["ha"])
        self.assertTrue(s["ha"]["token_set"])
        self.assertNotIn(TOKEN, json.dumps(s))

    async def test_pages_served(self):
        for path in ("/", "/settings", "/static/live.js", "/static/settings.js", "/static/app.css"):
            self.assertEqual((await self.client.get(path)).status, 200, path)

    async def test_session_drives_and_restores(self):
        r = await self.client.post("/api/start")
        self.assertEqual(r.status, 200)
        self.assertEqual(self.fake.states[HELPER]["state"], "on")
        ws = await self.client.ws_connect("/ws")
        for _ in range(10):
            await ws.send_json({"type": "levels", "bass": 1.0, "mid": 0.5, "treble": 0.9})
            await asyncio.sleep(0.05)
        await self.wait_for(lambda: self.fake.states["light.cinema_light"]["state"] == "on")
        self.assertEqual(self.fake.states["light.tv_ambient_light"]["attributes"]["brightness"], 255)
        driven = {c[2] for c in self.fake.calls}
        self.assertTrue({"light.tv_ambient_light", "light.single_colored_light", "light.cinema_light"} <= driven)
        status = await (await self.client.get("/api/status")).json()
        tv = next(l for l in status["lights"] if l["entity_id"] == "light.tv_ambient_light")
        self.assertEqual(tv["brightness"], 100)

        await self.client.post("/api/stop")
        await self.wait_for(lambda: self.fake.states[HELPER]["state"] == "off")
        self.assertEqual(self.fake.states["light.tv_ambient_light"]["state"], "off")      # was off
        self.assertEqual(self.fake.states["light.cinema_light"]["state"], "off")          # was off
        self.assertEqual(self.fake.states["light.single_colored_light"]["attributes"]["brightness"], 200)
        await ws.close()

    async def test_watchdog_stops_silent_session(self):
        await self.client.post("/api/start")
        await self.wait_for(lambda: not self.engine.active, timeout=5)
        await self.wait_for(lambda: self.fake.states[HELPER]["state"] == "off")
        self.assertIn("no audio", self.engine.last_stop_reason)

    async def test_helper_off_in_ha_ends_session(self):
        await self.client.post("/api/start")
        ws = await self.client.ws_connect("/ws")
        await ws.send_json({"type": "levels", "bass": 0.5, "mid": 0.5, "treble": 0.1})
        n = len(self.fake.calls)
        await self.fake.set_state(HELPER, "off")
        await self.wait_for(lambda: not self.engine.active)
        self.assertIn("Home Assistant", self.engine.last_stop_reason)
        helper_calls = [c for c in self.fake.calls[n:] if c[2] == HELPER]
        self.assertEqual(helper_calls, [])            # did not fight the user's off
        await ws.close()

    async def recv_state(self, ws):
        while True:
            msg = await asyncio.wait_for(ws.receive_json(), 2)
            if msg.get("type") == "state":
                return msg

    async def test_single_source_and_take_control(self):
        await self.client.post("/api/start")
        ws1 = await self.client.ws_connect("/ws")
        ws2 = await self.client.ws_connect("/ws")
        await ws1.send_json({"type": "levels", "bass": 0.9, "mid": 0, "treble": 0})
        await self.wait_for(lambda: self.engine.levels["bass"] == 0.9)
        await ws2.send_json({"type": "levels", "bass": 0.1, "mid": 0, "treble": 0})
        await asyncio.sleep(0.2)
        self.assertEqual(self.engine.levels["bass"], 0.9)          # ws2 is not the source

        await ws2.send_json({"type": "claim"})
        st = await self.recv_state(ws2)
        while not st["session"]["you_are_source"]:
            st = await self.recv_state(ws2)
        await ws1.send_json({"type": "levels", "bass": 0.3, "mid": 0, "treble": 0})
        await ws2.send_json({"type": "levels", "bass": 0.6, "mid": 0, "treble": 0})
        await self.wait_for(lambda: self.engine.levels["bass"] == 0.6)
        await asyncio.sleep(0.2)
        self.assertEqual(self.engine.levels["bass"], 0.6)          # ws1 was ignored
        st1 = await self.recv_state(ws1)
        self.assertFalse(st1["session"]["you_are_source"])

        await ws2.close()                                          # source leaves...
        await self.wait_for(lambda: self.engine.source is None)
        status = await (await self.client.get("/api/status")).json()
        self.assertFalse(status["session"]["source_connected"])
        self.assertTrue(status["active"])                          # ...session waits for the watchdog
        await ws1.send_json({"type": "levels", "bass": 0.4, "mid": 0, "treble": 0})
        await self.wait_for(lambda: self.engine.levels["bass"] == 0.4)   # next sender takes over
        await ws1.close()

    async def test_claim_without_session_is_ignored(self):
        ws = await self.client.ws_connect("/ws")
        await ws.send_json({"type": "claim"})
        st = await self.recv_state(ws)
        self.assertFalse(st["active"])
        self.assertIsNone(self.engine.source)
        await ws.close()

    async def test_levels_ignored_when_idle(self):
        ws = await self.client.ws_connect("/ws")
        await ws.send_json({"type": "levels", "bass": 1, "mid": 1, "treble": 1})
        await asyncio.sleep(0.3)
        self.assertEqual(self.fake.calls, [])
        await ws.close()

    async def test_stale_helper_is_released_on_connect(self):
        await self.fake.set_state(HELPER, "on")
        ha = self.client.server.app["ha"]
        ha.reload()
        await self.wait_for(lambda: self.fake.states[HELPER]["state"] == "off")

    async def test_light_crud_and_validation(self):
        r = await self.client.post("/api/lights", json={"entity_id": "switch.plug", "band": "mid", "threshold": 70})
        self.assertEqual(r.status, 201)
        body = await r.json()
        self.assertEqual((body["kind"], body["band"], body["threshold"]), ("onoff", "mid", 70))
        self.assertEqual((await self.client.post("/api/lights", json={"entity_id": "switch.plug"})).status, 400)
        self.assertEqual((await self.client.post("/api/lights", json={"entity_id": "sensor.x"})).status, 400)
        self.assertEqual((await self.client.post("/api/lights", json={"entity_id": "not an id"})).status, 400)
        r = await self.client.put("/api/lights/switch.plug", json={"band": "treble", "threshold": 90})
        self.assertEqual((await r.json())["band"], "treble")
        self.assertEqual((await self.client.put("/api/lights/switch.plug", json={"band": "loud"})).status, 400)
        self.assertEqual((await self.client.delete("/api/lights/switch.plug")).status, 200)
        self.assertEqual((await self.client.delete("/api/lights/switch.plug")).status, 404)
        info = await (await self.client.get("/api/entity/light.cinema_light")).json()
        self.assertEqual((info["exists"], info["kind"]), (True, "onoff"))
        info = await (await self.client.get("/api/entity/light.nope")).json()
        self.assertFalse(info["exists"])

    async def test_band_validation_and_persistence(self):
        r = await self.client.put("/api/settings", json={"bands": {"bass": [30, 200], "mid": [200, 3000], "treble": [3000, 15000]}})
        self.assertEqual((await r.json())["bands"]["bass"], [30, 200])
        saved = json.loads(self.settings.path.read_text())
        self.assertEqual(saved["bands"]["mid"], [200, 3000])
        r = await self.client.put("/api/settings", json={"bands": {"bass": [300, 200], "mid": [1, 2], "treble": [1, 2]}})
        self.assertEqual(r.status, 400)

    async def test_env_locked_field_rejected_by_api(self):
        self.settings.env["helper"] = "input_boolean.from_env"
        r = await self.client.put("/api/settings", json={"ha": {"helper": "input_boolean.other"}})
        self.assertEqual(r.status, 400)
        self.assertIn("HA_HELPER", (await r.json())["error"])
        s = await (await self.client.get("/api/settings")).json()
        self.assertEqual((s["ha"]["helper"], s["ha"]["locked"]), ("input_boolean.from_env", ["helper"]))

    async def test_bad_token_reports_auth(self):
        await self.client.put("/api/settings", json={"ha": {"token": "wrong"}})
        ha = self.client.server.app["ha"]
        await self.wait_for(lambda: ha.status.startswith("auth rejected"))
        self.assertFalse(ha.connected)
        r = await self.client.post("/api/start")
        self.assertEqual(r.status, 503)


if __name__ == "__main__":
    unittest.main()
