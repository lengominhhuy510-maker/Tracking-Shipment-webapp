# TASK-11 — Design

## Status

planned

## Lane

high-risk

## Contract (trỏ nguồn, không copy dài)

- **`IMOResolverResult`** shape + enum `error_code` — **IC§4.1** normative.
- **/scrape-jobs** request/poll — **IC§3.3** (đã dựng TASK-10).
- **`resolve_leg()` pseudo-code + fallback manual_required** — **Spec §6.7a**.
- **Mirror leg→shipments** — **Spec §4.8/§4.1**; ranh giới Python-ghi-DB — **IC§0.1**.
- **normalize_vessel_name** trước khi query/cache — **IC§9**.

## Flow

```
POST /shipments (không imo)
  → cache vessel_registry (normalize_vessel_name)? 
      hit  → resolve_leg(..., 'cache_hit')
      miss → background: scrape_client.resolve_imo
               → POST /scrape-jobs → poll 3s / timeout 120s
               → IMOResolverResult ok  → resolve_leg(..., 'scrape')
               → error_code            → mark_leg_manual(leg_id, error_code)
resolve_leg (1 transaction):
  UPDATE shipment_legs (imo, mmsi, 'resolved', imo_resolved_via)
  if leg.is_active_leg: mirror shipments (imo/mmsi/status/via, onboarding_error=NULL)
sau đó: ResubscribeSignal (TASK-04) + broadcast_onboarding_update (noop/thật)
```

## Quyết định trích từ PROGRESS.md

- **Nguồn ghi duy nhất:** mọi ghi định danh tàu đi qua `resolve_leg()` ngay từ TASK-11 (schema-ahead `shipment_legs` từ TASK-02) — tránh refactor khi build rollover/transit sau.
- **Cùng 1 transaction** (`async with session.begin()`): leg và mirror shipments không bao giờ lệch nhau — data integrity gate.
- **Deterministic, không LLM:** lọc tàu trùng tên bằng voyage/flag trong code — phân biệt với TASK-12 (agentic, cửa MCP).
- **Poll model:** Python chủ động poll + tự ghi DB; Node stateless trả JSON (IC§0.1).
- Không adapter-hóa `leg_service` (domain logic nội bộ — ranh giới Option 1.5 v0.9.12); `scrape_client` là client mỏng theo công thức 3 mảnh (typed model + client nhỏ + error mapping).

## Files

MODIFY `playwright-mcp/src/jobs/imo_resolve.ts`; NEW `backend/app/services/scrape_client.py`, `backend/app/services/leg_service.py`, `backend/tests/test_leg_service.py`; MODIFY `backend/app/api/shipments.py`.
