# TASK-07 — Design

## Status

implemented

## Lane

high-risk

## Data flow

```text
FastAPI lifespan
  ├─ weather_poll.run()
  │    └─ on_sea shipment + current lat/lon
  │         → integrations.open_meteo.fetch_conditions()
  │         → parsed WeatherConditions
  │         → upsert env_conditions weather/current fields
  │         ↘ timeout/error: log; leave cached row unchanged
  └─ tide_poll.run()
       └─ on_sea shipment + POD
            → geocode_port(POD) from local WPI CSV
            → daily quota guard (max 10 UTC-day calls)
            → integrations.stormglass.fetch_tide_extremes()
            → parsed TideConditions
            → upsert env_conditions tide fields
            → eta_in_tidal_window()
            ↘ false: broadcast_tidal_alert()
            ↘ missing key/error/quota: log; leave cached row unchanged
```

## Contracts

- `geocode_port(name) -> tuple[float, float, str] | None` with normalized alias mapping for VNCLI, SGSIN, HKHKG, TWKHH and fuzzy fallback when RapidFuzz is installed.
- `eta_in_tidal_window(eta, extremes, window_hours) -> bool | None`; `None` means the question cannot be answered (missing/invalid ETA/extremes), not “outside window.”
- Open-Meteo uses one Marine request for wave/current and one Forecast request for wind because the active provider APIs expose wind separately; a single shared client call groups them as one logical weather fetch.
- StormGlass uses `Authorization` header and `/v2/tide/extremes/point` with destination coordinates.

## Persistence and ownership

Workers upsert `EnvConditions` by primary key. Existing provider fields are untouched when a fetch fails. External clients contain transport/auth/parsing only; they never import SQLAlchemy models or broadcast functions.

## Quota model

The app contract is one uvicorn process. Tide polling keeps an in-memory UTC-date counter and stops issuing provider requests after 10 calls. A restart can reset the count, so production-grade distributed quota persistence remains outside MVP; the default 12-hour cadence and 3–5 shipment limit are the primary quota controls.

## Alert semantics

Only high-tide extrema (`type` containing `high`) define the illustrative arrival window. If payload types are absent, all valid extrema are considered. The nearest valid extreme is included in `tidal_alert`; invalid or empty data yields no alert.
