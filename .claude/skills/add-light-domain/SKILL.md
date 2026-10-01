---
name: add-light-domain
description: Add support for a new Home Assistant entity domain (e.g. another switch-like domain) as a controllable light. Use when the user wants to drive a new kind of HA entity.
argument-hint: "<domain> [dimmable|onoff]"
---

# Add an entity domain

Domain handling is spread over a few spots in `src/app.py`; update all of them:

1. `ONOFF_DOMAINS` / `SUPPORTED_DOMAINS` (top of file). A domain in `ONOFF_DOMAINS` is
   driven by threshold + hysteresis; a dimmable one needs brightness handling in `Engine`.
2. `service_for()` has its own hard-coded domain tuple. Add the domain there, or it falls
   back to `homeassistant.turn_on/off`.
3. `kind_from_state()` if the kind can't be derived from the domain alone.
4. Snapshot/restore (`Engine._snap` and the restore path): confirm the domain's attributes
   are restored on session end (ADR 0003).
5. Frontend: `src/static/settings.js` if it lists or validates domains.
6. Tests: add cases in `src/tests/test_app.py` (`MappingTests` for kind, `E2ETests` using
   `FakeHA` for service calls and restore).
7. Document in `README.md` if user-visible; then run the `verify` skill.
