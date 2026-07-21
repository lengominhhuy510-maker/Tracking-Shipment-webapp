# TASK-07 — Validation

## Status

implemented (StormGlass live smoke pending key)

## Lane

high-risk

| Check | Command / evidence | Result |
| --- | --- | --- |
| Geocode TDD | `pytest tests/test_geocode.py -v` | PASS (5) — RED watched first (ModuleNotFoundError), then GREEN |
| Tide TDD | `pytest tests/test_tide.py -v` | PASS (8) — RED watched first, incl. `nearest_high_tide` |
| Worker offline tests | `pytest tests/test_weather_poll.py tests/test_tide_poll.py -v` | PASS (12) — upsert, cache-on-failure, quota 10/day + UTC reset, missing key, alert only when outside window, weather/tide field isolation |
| Lint | `ruff check app tests` | PASS ("All checks passed!") |
| Compile/type smoke | `python -m compileall -q app` | PASS |
| Full backend tests | `pytest -q` | PASS — 116 passed, 6 skipped |
| Open-Meteo smoke | live fetch at 10.2,107.3 (offshore Vũng Tàu), no key | PASS — wind 14.7 kn, wave 0.7 m, current 0.92 kn @103°, tz-aware UTC timestamp (2026-07-21) |
| Missing StormGlass key | `tide_poll._poll_once()` with empty key | PASS — logs `thiếu STORMGLASS_API_KEY`, returns 0, no crash; `app.main` imports with all 4 workers wired |
| StormGlass smoke | live tide fetch and DB query | NOT RUN — `STORMGLASS_API_KEY` empty in `.env`; see smoke-key checklist |
| Import boundary | grep `httpx` under `app/` | PASS — only `app/integrations/open_meteo.py` and `app/integrations/stormglass.py` |

## Smoke-key checklist

- [ ] With `STORMGLASS_API_KEY`, invoke one tide cycle for an on-sea shipment.
- [ ] Confirm `env_conditions.tide_extremes`, station metadata, and `tide_fetched_at` are populated.
- [ ] Confirm provider calls remain within 10 per UTC day.
- [ ] Confirm an out-of-window ETA emits one `tidal_alert` from `tide_poll.py`.
