# TASK-07 — Execution Plan

## Status

implemented

## Lane

high-risk

## Steps

1. TDD `test_geocode.py`: alias, accents/case, exact UN/LOCODE/name, unknown port, missing CSV; implement `services/geocode.py` and five-port CSV.
2. TDD `test_tide.py`: inside/outside boundary, timezone strings, high-vs-low filtering, invalid/empty inputs; implement `core/tide.py`.
3. Add narrow provider clients under `app/integrations/` with typed parsed results and mapped integration errors.
4. Implement `weather_poll.py`: select eligible shipments, fetch, upsert only on success, commit per successful cycle, log failures.
5. Implement `tide_poll.py`: missing-key guard, geocode, UTC daily quota cap, upsert, tidal-window check, unique alert producer.
6. Wire weather/tide workers into `main.py` lifespan.
7. Run targeted TDD proof, worker tests, ruff, compile/type smoke, full pytest, live Open-Meteo smoke, and missing-key app-start smoke. Run StormGlass smoke only if a key is available without reading or exposing user-owned secret files.

## Stop conditions

- Any worker crash caused by a missing key/provider failure.
- Any path overwrites cached provider values after a failed fetch.
- StormGlass request count can exceed 10 in one UTC day in the supported single-process runtime.
- HTTP/auth/parsing leaks into domain services or DB logic leaks into integrations.
- Lint, compile, or tests remain red.
