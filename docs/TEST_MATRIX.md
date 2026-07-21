# Test Matrix

This file maps product behavior to proof.

**Rules:**

- **Append only.** Add a row per story or behavior. Never delete rows — mark them
  `retired` instead.
- **Never mark a row implemented** until tests or validation evidence actually
  exist.
- **Flag conflicts.** If a change would alter behavior an existing row already
  covers, mark that row `changed` and note the conflict rather than silently
  editing it.

## Status Values

| Status | Meaning |
| --- | --- |
| planned | Accepted as intended behavior, not implemented |
| in_progress | Actively being built |
| implemented | Implemented and proof exists |
| changed | Contract changed after earlier implementation |
| retired | No longer part of the product contract |

## Matrix

| Story ID | Scenario | Given | When | Then | Risk Flags | Lane | Status |
| --- | --- | --- | --- | --- | --- | --- | --- |
| US-000 | Example: health check responds | the service is running | a client requests `/health` | it returns 200 OK | none | tiny | planned |
| TASK-02 | Schema đủ 10 bảng + constraint enforced | DB rỗng, Postgres chạy | `alembic upgrade head` + seed | 10 bảng + partial unique index `uq_legs_one_active WHERE is_active_leg` tồn tại; CHECK enum reject giá trị sai; seed idempotent (2 lần vẫn 4 lô + 2 user) | data model, migration, multi-domain | high-risk | planned |
| TASK-10 | Scrape infra nhận job, không chạm Postgres | redis + playwright-mcp up | `POST /scrape-jobs {type:"imo_resolve"}` | trả `{job_id}` 202; `GET /:id` trả status/result; container KHÔNG có `DATABASE_URL` (IC§0.1); MCP SSE port 3001 phản hồi | external systems, public contract, audit/security | high-risk | planned |
| TASK-11 | resolve_leg mirror leg→shipments 1 transaction | lô seed 1 leg active pending | `resolve_leg(imo, mmsi)` / `mark_leg_manual(error)` | leg + shipments cùng resolved/manual_required, mirror khớp, cùng transaction; ResubscribeSignal + broadcast_onboarding_update bắn | external systems, data model, weak proof | high-risk | planned |
| TASK-12 | Carrier ETA không chặn tracking | mock MCP/LLM raise lỗi | onboarding chạy fetch_carrier_eta | shipment vẫn `resolved`, `eta_current` không đổi; lô thiếu `eta_original` vẫn AIS tracking; chỉ ghi `eta_original` source `carrier_scrape` khi thành công | external systems, weak proof, existing behavior | high-risk | planned |
| TASK-13 | Email proposal idempotent + \Seen ordering | 4 mail fixture IC§14 | xử lý cùng mail 2 lần | chỉ 1 proposal (unique `(source_email_id, shipment_id)`); commit `processed_emails` TRƯỚC `STORE \Seen`; allowlist kép suffix-match; rollover tạo leg mới + `resolve_and_activate_leg` | external systems, audit/security, data model, weak proof | high-risk | planned |
| TASK-14 | Auth coverage toàn bộ /api/v1/* | app chạy, không cookie | duyệt `app.routes` + gọi endpoint/WS | mọi route `/api/v1/*` có `get_current_user`; không cookie → 401 JSON; WS → close 4401; JWT round-trip/hết hạn/sai secret đúng; stub TASK-03 biến mất | auth, authorization, public contract | high-risk | planned |
| TASK-16 | Auto-forward chỉ tới whitelist env | mail hợp lệ, lô auto_email vs manual | proposal được tạo | auto_email → forward đúng `AUTO_FORWARD_RECIPIENTS` + log (recipient, message_id, shipment_id, ts); manual → không forward; địa chỉ nhận KHÔNG BAO GIỜ lấy từ nội dung mail | external systems, audit/security | high-risk | planned |
| TASK-07 | Weather/current/tide poll giữ cache khi provider lỗi | lô `on_sea` có vị trí/POD và `env_conditions` có thể đã có cache | weather/tide poll chạy với provider success, timeout, thiếu key và quota đủ/cạn | success upsert đúng field + timestamp; lỗi/thiếu key/quota không xóa cache và không crash app; StormGlass ≤10 call/ngày; chỉ tide poll phát `tidal_alert` khi ETA ngoài cửa sổ | external systems, data model, weak proof | high-risk | implemented |

## Evidence Rules

- Unit proof covers pure domain and application rules.
- Integration proof covers backend enforcement, data integrity, provider
  behavior, jobs, or service contracts.
- E2E proof covers user-visible end-to-end flows.
- Platform proof covers shell, deployment, mobile, desktop, or runtime behavior
  that cannot be proven in lower layers.
- A story can be implemented without every proof type if its story packet
  explains why.
