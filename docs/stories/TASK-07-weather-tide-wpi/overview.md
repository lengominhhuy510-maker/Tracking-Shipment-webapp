# TASK-07 — Weather/current + tide poll + WPI geocode

## Status

implemented

## Lane

high-risk

## Current behavior

- ETA recompute reads `env_conditions`, but no worker populates weather/current/tide fields.
- `eta_service.py` treats missing `app.services.geocode` as `no_pod_coords`.
- FastAPI lifespan starts AIS and trail workers only.

## Target behavior

- Local WPI subset resolves demo port aliases to `(lat, lng, un_locode)`.
- Open-Meteo polling updates wind, wave, and current for each `on_sea` shipment with a known current position, preserving cached values on failure.
- StormGlass polling updates destination tide extremes for `on_sea` shipments, never exceeds 10 requests per UTC day in this single process, preserves cached values on failure, and is the only producer of `tidal_alert`.
- Missing `STORMGLASS_API_KEY` logs a clear warning while the app and other workers continue.
- Both polls start and cancel through FastAPI lifespan.

## Hard boundaries

- External HTTP lives under `app/integrations/`; workers own DB writes, quota state, scheduling, and broadcasts.
- Provider payloads do not flow into domain code unparsed.
- API keys come only from `settings`; logs never include key values.
- No retry loop beyond the normal poll cadence.

## Non-goals

- No full WPI download, chart-datum correction, navigation-grade UKC, or exact harbor hydrodynamics.
- No distributed quota coordination or multi-process worker support.
- No changes to ETA formulas, schemas, migrations, frontend labels, or StormGlass subscription behavior.
