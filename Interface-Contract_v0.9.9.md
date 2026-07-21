# Interface Contract v0.9.9 — hợp đồng giữa các thành phần

**Trạng thái:** ĐÃ CHỐT (normative). Tài liệu này + Spec v0.9.19 là **2 input đủ** cho plan 18 task `TASK-00..17` (TASK-17 = E2E offline deterministic).

**Quan hệ với Spec:** Spec v0.9.19 là decision doc — chốt *làm gì, bằng gì, vì sao*. Tài liệu này chốt *hình dạng cụ thể* của mọi ranh giới giữa các thành phần: schema, API, message format, signature, config. Khi 2 tài liệu lệch nhau về **quyết định** thì Spec thắng; lệch về **hình dạng interface** thì tài liệu này thắng. Các chỗ tài liệu này **vá/bổ sung** Spec (không chỉ điền chỗ trống) được đánh dấu **[VÁ SPEC]** — ba chỗ lớn gom ở mục 0, hai chỗ nhỏ đánh dấu tại chỗ (mục 3.3: cửa REST chỉ chở `imo_resolve`; mục 4.2: thêm trường `new_vessel_name`). Spec v0.9.12 chỉ chốt tường minh vận hành/tính toán + thêm AIS replay + Known Limitations (xem changelog v0.9.11→v0.9.12 của spec), không đổi interface theo cách phá vỡ — contract này giữ version v0.9.9 và nguyên hiệu lực; các bổ sung đợt v0.9.12 (enum `skipped_reason` mở rộng, ràng buộc idempotency `agent_proposals`, biến `AIS_MODE`, chính sách WS frontend) là **additive**, đánh dấu **[v0.9.12]** tại chỗ.

---

## 0. [VÁ SPEC] Ba lỗ hổng phát hiện khi rà spec — quyết định vá

### 0.1 Node KHÔNG BAO GIỜ chạm Postgres (sửa mâu thuẫn §6.7d ↔ §6.7a)

**Mâu thuẫn:** sơ đồ §6.7d ghi Node worker "ghi kết quả vào Postgres (vessel_registry/shipments)", nhưng §6.7a quy định mọi kết quả phân giải phải đi qua `resolve_leg()` — hàm **Python**, 1 transaction, để giữ pattern mirror. Hai đường ghi song song sẽ phá mirror (Node ghi thẳng `shipments` bỏ qua `shipment_legs`).

**CHỐT:** đối xứng hóa ranh giới ngôn ngữ — Python không chạm Redis (đã có trong spec), **Node không chạm Postgres** (vá mới):
- Container `playwright-mcp` **không có DB credentials** (không có `DATABASE_URL` trong env của nó).
- Node chỉ trả kết quả JSON qua `GET /scrape-jobs/{id}` (mục 5.2). Python poll về, tự validate Pydantic, tự ghi `vessel_registry`, tự gọi `resolve_leg()`.
- Sơ đồ §6.7d dòng "→ ghi kết quả vào Postgres" đọc là "→ trả kết quả về Python (qua polling), Python ghi Postgres". Mũi tên "ghi kết quả" từ `playwright-mcp` → `db` trong sơ đồ §3.7 cũng đọc theo cách này.

### 0.2 Thêm 2 bảng nhỏ: `env_conditions` (bảng 9) + `processed_emails` (bảng 10)

**Lỗ hổng:** spec mô tả poll Open-Meteo/StormGlass (§6.2) và ETA Tầng 2 đọc wind/wave/current (§6.3) nhưng **không có bảng nào chứa** dữ liệu môi trường — Tầng 2 và cảnh báo tidal window không có input trace được. Tương tự, Email Agent poll mailbox định kỳ nhưng spec không nói gì về **dedup** — mỗi lần poll sẽ xử lý lại toàn bộ mail cũ.

**CHỐT:** thêm 2 bảng (DDL ở mục 2). Research cache (§6.3d) **không cần bảng mới** — query thẳng `research_findings WHERE route_key = ? AND created_at > now() - TTL`; bảng có sẵn vừa là log vừa là cache, trace được.

### 0.3 Quy tắc chuyển `shipments.status` (milestone engine)

**Lỗ hổng:** spec có enum `new/on_sea/arrived/delivered` + công thức map milestone (đã chốt ở contract cũ, giữ nguyên ở mục 1.2) nhưng **không nói ai/lúc nào set** các giá trị đó.

**CHỐT:**

| Chuyển | Trigger | Ai quyết |
|---|---|---|
| `new → on_sea` | User nhập `atd` qua `PATCH /shipments/{id}` → hệ tự flip status trong cùng request | Người (nhập ATD) |
| `on_sea → arrived` | Hệ **đề xuất** khi: vị trí AIS trong bán kính `ARRIVAL_RADIUS_KM` quanh tọa độ POD (geocode WPI) **VÀ** `current_sog < SOG_MIN_KNOT` kéo dài ≥ 30 phút → đẩy WS `status_change_suggested` + badge UI. User bấm xác nhận → `PATCH status=arrived` | Hệ đề xuất, **người xác nhận** |
| `arrived → delivered` | Chỉ tay: `PATCH status=delivered` (không có tín hiệu tự động đáng tin cho việc giao hàng nội địa) | Người |
| `delivered_at` | Set tự động = `now()` khi status chuyển sang `delivered` (neo cleanup 14 ngày, §4.9) | Hệ |

Chuyển ngược (VD `arrived → on_sea` khi bấm nhầm) cho phép qua PATCH với role bất kỳ, ghi log; không cần máy trạng thái cứng ở MVP.

---

## 1. Enum & trạng thái — bảng tổng hợp (nguồn sự thật duy nhất)

### 1.1 Toàn bộ enum — lưu dạng `text` + `CHECK` constraint

**Quy ước chung:** giá trị enum là ASCII không dấu, snake_case. ⚠️ Deviation nhỏ so spec: `trung_bình`/`thấp` (có dấu, §4.5) đổi thành `trung_binh`/`thap` — dấu tiếng Việt trong giá trị enum là nguồn bug so khớp/encoding. UI hiển thị nhãn có dấu, DB lưu không dấu.

| Field | Bảng | Giá trị CHECK |
|---|---|---|
| `incoterm` | `shipments` | `EXW`,`FCA`,`FAS`,`FOB`,`CFR`,`CIF`,`CPT`,`CIP`,`DAP`,`DPU`,`DDP` |
| `shipment_direction` | `shipments` | `import` \| `export` |
| `monitoring_mode` | `shipments` | `auto_email` \| `manual` |
| `shipment_type` | `shipments` | `direct` \| `transit` (default `direct`) |
| `status` | `shipments` | `new` \| `on_sea` \| `arrived` \| `delivered` (default `new`) |
| `onboarding_status` | `shipments`, `shipment_legs` | `pending` \| `resolved` \| `manual_required` (default `pending`) |
| `onboarding_error` | `shipments`, `shipment_legs` | `captcha` \| `not_found` \| `ambiguous_name` \| `timeout` \| `login_required` \| NULL |
| `imo_resolved_via` | `shipments`, `shipment_legs` | `cache_hit` \| `deterministic_scrape` \| `manual` \| NULL |
| `eta_original_source` | `shipments` | `carrier_scrape` \| `manual` \| NULL |
| `source` | `eta_history` | `original` \| `ais_recompute` \| `weather_adjusted` \| `email_agent` \| `manual` |
| `status` | `agent_proposals` | `pending` \| `approved` \| `rejected` (default `pending`) |
| `relevance`, `confidence` | `research_findings` | `cao` \| `trung_binh` \| `thap` |
| `resolved_via` | `vessel_registry` | `manual` \| `ais_static` \| `vesselfinder` |
| `provider` | `users` | `google` \| `microsoft` |
| `role` | `users` | `user` \| `admin` (default `user`) |
| `outcome` | `processed_emails` | `proposals_created` \| `no_match` \| `rejected_allowlist` \| `parse_failed` |
| `email_type` | (Pydantic, không lưu enum DB) | `rollover` \| `vessel_change` \| `transit_delay` \| `other` |

**Nhóm Incoterm (derived, không lưu):** nhóm E/F = `EXW,FCA,FAS,FOB`; nhóm C/D = `CFR,CIF,CPT,CIP,DAP,DPU,DDP`. Hàm duy nhất `derive_monitoring_mode(direction, incoterm) -> Literal["auto_email","manual"] | raises UnsupportedCombination` cài bảng §5 spec: import×E/F=`auto_email`, import×C/D=`manual`, export×C/D=`auto_email`, export×E/F=**raise** (400 ở API, ẩn ở UI). Mọi module dùng hàm này, không tự cài bảng riêng.

### 1.2 Map milestone UI ← trạng thái DB (đã chốt — spec §6.1 đã sửa theo ở v0.9.10, hết mâu thuẫn)

Không thêm giá trị enum (`booked` không cần — lô chỉ được tạo khi đã có Booking Confirmation/B/L, nên `new` mặc nhiên bao hàm `[Nhận B/L]`). Milestone suy diễn:

| `status` | `atd` | `shipment_type` | Milestone hiển thị |
|---|---|---|---|
| `new` | NULL | any | `[Nhận B/L]` (current) |
| `on_sea` | NOT NULL | `direct` | `[Tàu khởi hành ATD]` (completed) → `[Đang trên biển]` (current) — cùng 1 status, 2 node phân biệt bằng thứ tự hiển thị |
| `on_sea` | NOT NULL | `transit` | Như trên + node `[Transit]` — chặng active hiển thị từ `shipment_legs.is_active_leg`, KHÔNG phải giá trị status riêng. Kể cả lúc đang chuyển tải, `status` vẫn là `on_sea` |
| `arrived` | NOT NULL | any | `[Cập cảng đích ETA]` |
| `delivered` | NOT NULL | any | `[Giao hàng]` |

---

## 2. DDL / Schema thực thi

### 2.1 Stack — ĐÃ CHỐT

- **SQLAlchemy 2.x async** (driver `asyncpg`) + **Alembic** migration. Model Python là nguồn schema; Alembic autogenerate + review tay từng migration.
- **Khóa kỷ luật ORM** (tránh magic, giữ tinh thần "không hộp đen" của spec):
  - Mọi relationship khai báo `lazy="raise"` — cấm lazy-load ngầm; muốn eager thì `selectinload()` tường minh tại query.
  - Enum = cột `TEXT` + `CheckConstraint` (bảng 1.1), KHÔNG dùng Postgres `ENUM` type (thêm giá trị giữa chừng không cần `ALTER TYPE`).
  - Query viết **2.0-style tường minh** (`select(...)`, `update(...)` import từ `sqlalchemy`), không dùng legacy `Query` API.
  - `resolve_leg()` / `switch_active_leg()` / `resolve_and_activate_leg()` viết bằng `update()` statement tường minh trong 1 `async with session.begin()` — thấy rõ từng UPDATE như pseudo-code §6.7a/§6.8.
- **[v0.9.12] Downgrade policy — FORWARD-ONLY:** MVP **KHÔNG hỗ trợ downgrade migration**. Mỗi thay đổi schema là 1 revision mới (`0002_...`, `0003_...`); hàm `downgrade()` trong mỗi revision để `raise NotImplementedError("forward-only migration, xem IC§2.1")` (hoặc `pass` kèm comment). Rollback schema ở production cần thiết kế downgrade path riêng hoặc restore backup (ghi Known Limitations §14 spec). Lý do: demo chỉ tiến lên head từ DB rỗng; viết downgrade đúng cho partial index/CHECK/mirror tốn công mà không dùng ở demo.

### 2.2 Mười bảng (8 bảng spec §4 + 2 bảng [VÁ SPEC] mục 0.2)

Cột của 8 bảng gốc lấy đúng theo spec §4.1-4.8 (không chép lại đây — spec là nguồn). Dưới đây chỉ chốt phần spec chưa chốt:

**Bảng 9 — `env_conditions` (mới):** 1 dòng/lô, upsert (giống pattern vị trí hiện tại §3.1b).

| Cột | Kiểu | Ghi chú |
|---|---|---|
| `shipment_id` | int PK, FK → shipments ON DELETE CASCADE | 1-1 với shipment |
| `wind_speed_kn` / `wave_height_m` / `current_speed_kn` / `current_direction_deg` | double precision NULL | Từ 1 lệnh gọi Open-Meteo Marine (§6.2) |
| `weather_fetched_at` | timestamptz NULL | Nhãn "dữ liệu có thể trễ" trên UI tính từ đây |
| `tide_extremes` | jsonb NULL | Raw response StormGlass extremes (list `{time, height, type}`) |
| `tide_station_name` / `tide_station_distance_km` | text / double NULL | Metadata trạm StormGlass trả kèm (§6.6) |
| `tide_fetched_at` | timestamptz NULL | Quota 10 call/ngày → có thể trễ tới 12h, hiển thị nhãn |

**Bảng 10 — `processed_emails` (mới):** dedup Email Agent + trace IMAP UID.

| Cột | Kiểu | Ghi chú |
|---|---|---|
| `message_id` | text PK | Message-ID header của mail trong hộp delegate — khóa dedup chính |
| `imap_uid` | bigint NULL | UID của mail trong folder IMAP (ổn định trong lifecycle mail, không đổi khi expunge mail khác). Dùng khi cần `STORE \Seen` lại nếu flag bị reset. NULL nếu IMAP server không trả UID (fallback theo `message_id`) |
| `imap_folder` | text NULL | Tên folder IMAP mail nằm (VD `INBOX`), trace + dùng khi `STORE` lại |
| `outcome` | text CHECK (bảng 1.1) | `rejected_allowlist` cũng ghi — trace mail bị lọc |
| `unmatched_containers` | jsonb NULL | List container lạ bị bỏ qua (log theo §7.1 v0.9.6 — đây chính là chỗ "ghi log nội bộ" spec yêu cầu) |
| `processed_at` | timestamptz | |
| `seen_set_at` | timestamptz NULL | Thời điểm `STORE \Seen` thành công — nếu NULL là chưa set được (poll kế sẽ retry) |

> **[v0.9.12] GIỮ NGUYÊN 4 giá trị `outcome` — KHÔNG thêm `partial_match`:** một mail vừa có container khớp vừa có container lạ (case §7.1 Mail 3) vẫn ghi `outcome='proposals_created'`; các container lạ đã lưu đầy đủ trong `unmatched_containers` (jsonb). Thêm `partial_match` sẽ **trùng thông tin** (nhìn `unmatched_containers` non-empty là biết có container lạ) mà không thêm giá trị query nào — nên chốt giữ 4 giá trị (`proposals_created | no_match | rejected_allowlist | parse_failed`). Quy tắc: có ≥1 proposal tạo được → `proposals_created` (bất kể có container lạ kèm hay không); không container nào khớp → `no_match`.

> **[v0.9.12] Idempotency `agent_proposals`:** unique `(source_email_id, shipment_id)` (mục 2.3) đảm bảo xử lý lại CÙNG mail (VD `\Seen` bị reset, hoặc replay test) KHÔNG tạo proposal trùng — INSERT trùng bị DB chặn, code bắt `IntegrityError` → coi như đã xử lý (idempotent). Kết hợp với dedup `processed_emails.message_id` (chặn ở tầng application trước khi extract) tạo 2 lớp: dedup chặn xử-lý-lại, unique constraint chặn ghi-trùng nếu lọt qua.

> Ghi chú: `imap_uid` + `imap_folder` + `seen_set_at` là cột trace/operational, không dùng query thường — không cần index. `message_id` vẫn là PK + khóa dedup chính.

### 2.3 Index bắt buộc

```sql
-- shipments
CREATE INDEX ix_shipments_status ON shipments(status);
CREATE INDEX ix_shipments_onboarding ON shipments(onboarding_status);
CREATE INDEX ix_shipments_mmsi ON shipments(mmsi) WHERE mmsi IS NOT NULL;
-- shipment_legs: DB tự ép "chỉ 1 leg active/lô" — không tin code suông
CREATE UNIQUE INDEX uq_legs_one_active ON shipment_legs(shipment_id) WHERE is_active_leg;
CREATE INDEX ix_legs_shipment ON shipment_legs(shipment_id);
-- time-series
CREATE INDEX ix_trail_shipment_time ON vessel_trail(shipment_id, recorded_at);
CREATE INDEX ix_etahist_shipment_time ON eta_history(shipment_id, recorded_at);
-- research cache lookup (mục 0.2)
CREATE INDEX ix_findings_route_time ON research_findings(route_key, created_at);
-- proposals inbox
CREATE INDEX ix_proposals_status ON agent_proposals(status) WHERE status = 'pending';
-- [v0.9.12] idempotency: xử lý lại cùng 1 mail cho cùng 1 container KHÔNG tạo proposal trùng.
-- ⚠️ agent_proposals (spec §4.4) KHÔNG có cột container_no trần — mỗi proposal = 1 container khớp,
--    số container nằm trong extracted_json (list) + shipment_id (lô khớp container đó). Khóa idempotency
--    tự nhiên đang có sẵn = cặp (source_email_id, shipment_id): 1 mail sinh tối đa 1 proposal / lô khớp.
--    Nếu build cần tách theo từng container thật (mail nhiều container cùng 1 lô — hiếm), THÊM cột
--    container_no text vào agent_proposals lúc TASK-02 rồi đổi unique sang (source_email_id, container_no).
--    Chốt MVP: dùng (source_email_id, shipment_id) — khớp thiết kế "1 proposal / lô / mail".
CREATE UNIQUE INDEX uq_proposals_email_shipment
  ON agent_proposals(source_email_id, shipment_id) WHERE shipment_id IS NOT NULL;
-- users (spec §4.7)
CREATE UNIQUE INDEX uq_users_provider_sub ON users(provider, provider_sub);
-- vessel_registry: tên tàu KHÔNG unique (trùng tên hợp lệ — nhiều IMO/tên, §4.6)
CREATE INDEX ix_registry_name ON vessel_registry(vessel_name);
```

### 2.4 FK `ON DELETE`

- Con của `shipments` (`eta_history`, `vessel_trail`, `agent_proposals`, `research_findings`, `shipment_legs`, `env_conditions`): **CASCADE** — xóa lô demo là dọn sạch, không rác mồ côi.
- FK tới `users` (`agent_proposals.decided_by`, `research_findings.verified_by`): **RESTRICT** — không được xóa user đã có dấu vết audit (đúng mục tiêu audit trail §3.8; user không dùng nữa thì để nguyên dòng).

---

## 3. REST API

### 3.1 Quy ước chung

- **Prefix:** mọi API dưới `/api/v1/...`. **Ngoại lệ:** `/auth/*` ở root — khớp redirect URI đã hardcode đăng ký ở Google/Azure (`http://localhost:1476/auth/callback/{provider}`, spec §3.8). WebSocket tại `/ws`.
- **Status code:** 200 đọc/sửa OK · 201 tạo · 400 nghiệp vụ sai (kèm `code`) · 401 chưa đăng nhập · 403 sai role · 404 không thấy · 409 xung đột trạng thái (VD duyệt proposal đã decided) · 422 Pydantic validation (FastAPI mặc định) · 500 lỗi hệ.
- **Error envelope (mục 11 cũ — ĐÃ CHỐT):** giữ FastAPI-native, structured hóa `detail`:
  ```json
  { "detail": { "code": "SHIPMENT_NOT_FOUND", "message": "Không tìm thấy lô #42" } }
  ```
  Frontend switch theo `detail.code`. Riêng 422 giữ nguyên shape list mặc định của FastAPI (Pydantic errors). Danh mục `code`: `SHIPMENT_NOT_FOUND`, `PROPOSAL_NOT_FOUND`, `PROPOSAL_ALREADY_DECIDED`, `FINDING_NOT_FOUND`, `IMMUTABLE_FIELD`, `UNSUPPORTED_INCOTERM_COMBINATION`, `INVALID_CONTAINER_NO`, `ONBOARDING_NOT_RETRYABLE`, `UNAUTHENTICATED`, `FORBIDDEN`.
- **Auth:** mọi route `/api/v1/*` yêu cầu session JWT cookie (mục 10). 401 trả JSON như trên — **không server-redirect** (SPA tự điều hướng về màn login).

### 3.2 Bảng endpoint đầy đủ

| Method + Path | Request → Response | Ghi chú |
|---|---|---|
| `POST /api/v1/shipments` → 201 | `ShipmentCreate` → `ShipmentDetail` | Server: validate container ISO 6346 (mục 9) → `derive_monitoring_mode()` (400 `UNSUPPORTED_INCOTERM_COMBINATION` nếu export×E/F) → INSERT shipments + 1 dòng `shipment_legs` (leg_no=1, is_active_leg=true, onboarding_status=pending) trong 1 transaction → nếu payload có imo+mmsi (fallback tay) gọi luôn `resolve_leg(..., 'manual')`; nếu không, enqueue onboarding (POST /scrape-jobs sang Node) |
| `GET /api/v1/shipments?status=&direction=` | → `list[ShipmentListItem]` | Kèm vị trí hiện tại + eta_current + monitoring_mode + onboarding_status (đủ vẽ list + badge) |
| `GET /api/v1/shipments/{id}` | → `ShipmentDetail` | Embed: `legs: list[LegOut]`, `env: EnvConditionsOut \| null`, `recent_eta_history: list[EtaHistoryOut]` (5 dòng cuối) |
| `GET /api/v1/shipments/{id}/trail` | → `list[TrailPoint]` | Tối đa 12 điểm (rolling window §3.1b) |
| `GET /api/v1/shipments/{id}/eta-history` | → `list[EtaHistoryOut]` | Đầy đủ, cho biểu đồ "ETA theo thời gian" |
| `PATCH /api/v1/shipments/{id}` | `ShipmentPatch` → `ShipmentDetail` | **Whitelist sửa được:** `eta_original` (+tự set `eta_original_source=manual`), `atd` (tự flip `new→on_sea`, mục 0.3), `pol`/`pod` (chỉ khi `atd` IS NULL), `status` (chỉ nhận `arrived`/`delivered`/quay lui, mục 0.3), `bl_number`, `carrier`. **Cấm** (400 `IMMUTABLE_FIELD`): `imo`, `mmsi`, `onboarding_*` (mirror — chỉ qua resolve-manual), `monitoring_mode` (derived), `incoterm`+`shipment_direction` (đổi = tạo lô mới, tránh mode lệch lịch sử), `eta_current` (chỉ engine/proposal), `current_*` (chỉ AIS worker) |
| `POST /api/v1/shipments/{id}/retry-onboarding` → 202 | ∅ → `{leg_id, job_id}` | Chỉ khi leg active `manual_required` (400 `ONBOARDING_NOT_RETRYABLE` nếu không) — re-enqueue |
| `POST /api/v1/shipments/{id}/resolve-manual` | `{imo, mmsi}` → `ShipmentDetail` | Nhập tay → `resolve_leg(active_leg_id, imo, mmsi, 'manual')` |
| `GET /api/v1/agent-proposals?status=pending` | → `list[ProposalOut]` | Mặc định `pending`, cho hộp duyệt |
| `POST /api/v1/agent-proposals/{id}/approve` | `∅` → `ProposalOut` | 409 `PROPOSAL_ALREADY_DECIDED` nếu đã quyết. Ghi `decided_by` = user hiện tại + `decided_at`. Nếu extraction có `new_eta`: UPDATE `shipments.eta_current` + INSERT `eta_history(source='email_agent')`. Nếu có `new_vessel_name` (rollover, §6.8d): chạy chuỗi IMO Resolver tàu mới → `resolve_and_activate_leg()` → asyncio.Event resubscribe. Tất cả trong 1 transaction (trừ scrape — async, proposal chuyển `approved` ngay, leg mới `pending` cho tới khi resolver xong) |
| `POST /api/v1/agent-proposals/{id}/reject` | `{reason?}` → `ProposalOut` | Ghi `decided_by`/`decided_at` |
| `GET /api/v1/research-findings?shipment_id=&route_key=` | → `list[ResearchFindingOut]` | |
| `POST /api/v1/research-findings/{id}/verify` | `∅` → `ResearchFindingOut` | Set `verified=true`, `verified_by` = user hiện tại |
| `POST /api/v1/shipments/{id}/analyze` → 202 | `∅` → `{status:"queued"}` | Nút "Phân tích ngay" — trigger Agent A chạy 1 lần cho lô (mục 5.3); chạy background, kết quả ghi `eta_history.note` |
| `GET /auth/login/{provider}` | → 302 provider | Authlib `authorize_redirect` (spec §3.8) |
| `GET /auth/callback/{provider}` | → 302 `/` | Đổi code, tạo/update user, set cookie JWT (mục 10). Redirect về SPA shell công khai — an toàn với phân tích SameSite §3.8(B) |
| `GET /auth/me` | → `{id, email, name, role, provider}` | 401 nếu chưa login — SPA gọi lúc mount |
| `POST /auth/logout` | → 204 | Xóa cookie (Set-Cookie Max-Age=0) |

### 3.3 Scrape-jobs API (Node `playwright-mcp`, CHỈ nội bộ compose network)

**[VÁ SPEC — chốt chỗ §3.7 để mơ hồ]:** cửa REST chỉ chở **một loại job `imo_resolve`**. Carrier ETA Agent (LLM) đi **cửa MCP riêng** (SSE, LLM phía Python điều khiển từng bước) — KHÔNG đi qua scrape-jobs. Lý do: scrape-jobs là fire-and-forget + poll, hợp script deterministic; agentic cần vòng tương tác từng bước, nhét vào job queue là sai mô hình.

```
POST http://playwright-mcp:3000/scrape-jobs
  Request:  { "type": "imo_resolve",
              "payload": { "vessel_name": str, "voyage_no": str|null,
                           "pol": str|null, "pod": str|null } }
  Response 202: { "job_id": str }

GET http://playwright-mcp:3000/scrape-jobs/{job_id}
  Response 200: {
    "job_id": str,
    "status": "queued" | "running" | "succeeded" | "failed",
    "result": IMOResolverResult | null,     // chỉ khi succeeded — shape mục 4.1
    "error_code": "captcha"|"not_found"|"ambiguous_name"|"timeout"|"login_required" | null
  }                                          // error_code khớp enum onboarding_error 1-1
```

- Python poll mỗi 3s, timeout tổng 120s → coi như `failed/timeout`.
- `failed` → Python set leg `manual_required` + `onboarding_error=error_code` qua đúng đường fallback §6.7a (Python ghi, không phải Node — mục 0.1).

---

## 4. Pydantic schema — chốt type

Chuẩn chung: `datetime` luôn timezone-aware UTC (validator từ chối naive datetime). `HttpUrl` cho URL.

### 4.1 `IMOResolverResult` (Node trả về qua scrape-jobs, Python validate lại)

```python
class IMOResolverResult(BaseModel):
    vessel_name: str                          # tên đã normalize (mục 9)
    imo: str = Field(pattern=r"^\d{7}$")
    mmsi: str | None = Field(None, pattern=r"^\d{9}$")
    matched_voyage: str | None                # voyage khớp được khi lọc trùng tên
    confidence: Literal["cao", "trung_binh", "thap"]
    source_url: HttpUrl
```

### 4.2 `EmailExtraction` (LLM output, Email Agent §7.1)

```python
class EmailExtraction(BaseModel):
    containers: list[str] = Field(min_length=1)   # CHỐT tên field: `containers` thắng `cont` (§4.4)
                                                   # — mail nhắc nhiều container là case chuẩn §7.1
    from_voyage: str | None
    to_voyage: str | None
    new_eta: datetime | None                       # ISO8601, tz-aware
    new_vessel_name: str | None                    # [VÁ SPEC] §6.8d cần tên tàu mới để chạy
                                                   # resolve_and_activate_leg() nhưng §7.1 quên
                                                   # khai trong extraction schema — bổ sung
    reason: str
    email_type: Literal["rollover", "vessel_change", "transit_delay", "other"]
```

`agent_proposals.extracted_json` lưu nguyên `EmailExtraction.model_dump_json()` — 1 proposal/container khớp, nhưng `extracted_json` giữ list gốc đầy đủ để người duyệt thấy toàn cảnh mail.

### 4.3 `ResearchFindingOut` (Agent B trả cho Agent A, và là API response shape)

```python
class ResearchFindingOut(BaseModel):
    event: str
    relevance: Literal["cao", "trung_binh", "thap"]
    route_impact: str
    confidence: Literal["cao", "trung_binh", "thap"]
    sources: list[HttpUrl] = Field(min_length=1)   # CHỐT: list URL thuần, không {url,title}
```

**Chốt câu hỏi "confidence là chữ hay float":** cả 2 model dùng **cùng** `Literal["cao","trung_binh","thap"]` — khớp CHECK constraint của `research_findings`, đỡ 1 lần convert, và LLM trả 3 mức chữ ổn định hơn số 0-1.

### 4.4 `ShipmentCreate` (request POST /shipments)

```python
class ShipmentCreate(BaseModel):
    bl_number: str
    container_no: str                     # validator: normalize + ISO 6346 check-digit (mục 9)
    shipment_direction: Literal["import", "export"]
    incoterm: Literal["EXW","FCA","FAS","FOB","CFR","CIF","CPT","CIP","DAP","DPU","DDP"]
    carrier: str
    vessel_name: str
    voyage_no: str
    pol: str
    pod: str
    eta_original: datetime | None = None  # fallback nhập tay
    imo: str | None = Field(None, pattern=r"^\d{7}$")   # fallback tay — có cả imo+mmsi
    mmsi: str | None = Field(None, pattern=r"^\d{9}$")  # thì bỏ qua scrape
```

Các model Out (`ShipmentDetail`, `ShipmentListItem`, `LegOut`, `ProposalOut`, `EtaHistoryOut`, `TrailPoint`, `EnvConditionsOut`) = ánh xạ 1-1 cột DB tương ứng (bảng spec §4 + mục 2.2), không lặp lại ở đây; field datetime serialize ISO8601 `Z`. Response của research-findings dùng **`ResearchFindingOut`** (mục 4.3) — MỘT model duy nhất cho cả Agent B lẫn API, không tạo model song song.

---

## 5. AG2 tool / function-calling signature

### 5.1 Tool của Agent A (đăng ký function-calling)

```python
def get_shipment_state(shipment_id: int) -> ShipmentStateView:
    """Nạp state mới nhất từ DB: vị trí, SOG/COG, eta_original/current, atd,
    status, env_conditions, route_key. KHÔNG nạp transcript cũ (§6.4 stateless)."""

def recompute_eta(shipment_id: int) -> ETAComputeResult:
    """Chạy ETA Engine Tầng 1+2 (§6.3, thuần code). Trả breakdown:
    {eta_tier1, eta_tier2, avg_sog_kn, distance_remaining_nm,
     factors_applied: list[str],        # VD ["current_against_-8%", "wind_against_-5%", "rough_sea"]
     skipped_reason: str | None}        # [v0.9.12] enum mở rộng:
                                        #   "sog_below_min"   — guard 3b (tàu neo/cập cảng, SOG<ngưỡng)
                                        #   "no_valid_atd"    — guard 9b (atd null hoặc eta_original<=atd) → bỏ deviation, ETA vẫn tính
                                        #   "no_position"     — chưa có tọa độ AIS (current_lat/lon null) → skip recompute
                                        #   "no_pod_coords"   — POD chưa geocode được (geocode_port trả None) → skip recompute
    — LLM thấy được VÌ SAO ra con số (phòng thủ 'không hộp đen'). Dấu deviation: dương=trễ, âm=sớm (§6.3)."""

def get_tide_window(shipment_id: int) -> TideWindowResult:
    """Đọc env_conditions.tide_extremes (KHÔNG gọi StormGlass — quota do cron quản, §6.6).
    Trả {extremes: list[TideExtreme], eta_falls_in_window: bool | None, station_name,
    data_age_hours} — kèm tuổi dữ liệu để agent tự nêu nhãn 'có thể trễ'."""

def request_research(shipment_id: int, focus: str | None = None) -> ResearchFindingOut:
    """Kích vòng A↔B. focus = hướng search cụ thể khi A yêu cầu search lại
    (VD 'chỉ eo Malacca 48h tới'). Check cache route_key TTL 12h TRƯỚC khi
    gọi Agent B thật (§6.3d) — cache hit thì trả thẳng, không tốn search quota."""
```

### 5.2 Cơ chế A↔B — ĐÃ CHỐT

- **AG2 nested chat**: `request_research` bên trong khởi tạo chat A→B; B có đúng 1 tool `web_search(query: str) -> list[SearchResult]`.
- **B trả kết quả qua return value** (Pydantic `ResearchFindingOut`), KHÔNG tự ghi DB. **Code wrapper** (ngoài LLM) persist vào `research_findings` + set `route_key` — giữ nguyên tắc "agent không có đường ghi DB trực tiếp" (checklist 11b).
- **Giới hạn vòng lặp cài Ở CẢ HAI tầng:** `max_turns=3` tham số AG2 **và** hard cap 3 lần gọi `request_research`/lần chạy Agent A trong code wrapper — không tin riêng framework (API AG2 còn đổi giữa version, §9).
- **Sai format:** B trả sai Pydantic → retry đúng 1 lần (§6.3c) → vẫn sai thì wrapper trả finding rỗng `confidence=thap`, log, không crash vòng A.
- **Nhận định cuối của A** ghi vào `eta_history.note` (cột spec §4.2 đã chừa sẵn) — INSERT dòng `source='weather_adjusted'` mới nhất hoặc cập nhật note dòng cuối nếu ETA không đổi.

### 5.3 Cadence — ĐÃ CHỐT

Agent A chạy **scheduled 2 lần/ngày/lô `on_sea`** (khớp nhịp StormGlass/research §6.3c) + **nút "Phân tích ngay"** trên UI detail (trigger tay, không giới hạn — user chịu token). Agent A **KHÔNG** chạy theo từng bản tin AIS — ETA engine thuần code (mục 5.1 `recompute_eta` được AIS worker gọi trực tiếp không qua LLM) mới là lớp realtime; LLM là lớp diễn giải định kỳ. Đây là ranh giới chi phí quan trọng: bản tin AIS tới mỗi vài giây, gọi LLM theo nhịp đó là đốt token vô nghĩa.

---

## 6. WebSocket contract

- **Kênh:** 1 connection `/ws`, broadcast tất cả lô (3-5 lô không cần room/subscribe theo id). Client tự lọc theo `shipment_id` nếu đang ở màn detail.
- **Auth:** WS handshake đọc cùng session cookie (same-origin) — từ chối (close code 4401) nếu chưa login.
- **Envelope:**
  ```json
  { "type": "...", "shipment_id": 123, "ts": "2026-07-17T09:30:00Z", "data": { } }
  ```

| `type` | `data` | Nguồn phát |
|---|---|---|
| `position_update` | `{lat, lon, sog, cog, position_updated_at}` | AIS worker sau upsert |
| `eta_update` | `{eta_current, source, deviation_pct\|null}` | ETA engine sau ghi eta_history |
| `deviation_alert` | `{eta_current, eta_original, deviation_pct, threshold}` | Engine khi \|dev\| vượt ngưỡng (§6.3 bước 11) |
| `tidal_alert` | `{eta_current, nearest_window, message}` | Tide check sau cron StormGlass |
| `proposal_created` | `{proposal_id, proposed_action}` | Email Agent sau INSERT proposal |
| `onboarding_update` | `{onboarding_status, onboarding_error\|null, leg_id}` | Sau resolve_leg()/fallback |
| `status_change` | `{old_status, new_status}` | Sau PATCH status / auto-flip ATD |
| `status_change_suggested` | `{suggested: "arrived", reason}` | Arrival detector (mục 0.3) |

**Mapping hàm broadcast ↔ WS `type` (chuẩn tắc — TASK-04 tạo noop, TASK-06 điền body; task 05/07/11/13 import theo tên nguyên văn):**

| Hàm (module `app.services.broadcast`) | WS `type` |
|---|---|
| `broadcast_position(shipment_id, data)` | `position_update` |
| `broadcast_eta_update(shipment_id, data)` | `eta_update` |
| `broadcast_deviation_alert(shipment_id, data)` | `deviation_alert` |
| `broadcast_tidal_alert(shipment_id, data)` | `tidal_alert` |
| `broadcast_proposal_created(shipment_id, data)` | `proposal_created` |
| `broadcast_onboarding_update(shipment_id, data)` | `onboarding_update` |
| `broadcast_status_change(shipment_id, data)` | `status_change` |
| `broadcast_status_change_suggested(shipment_id, data)` | `status_change_suggested` |

Chữ ký cả 8: `async def <tên>(shipment_id: int, data: dict) -> None`. Lệch 1 chữ = gãy import toàn bộ task tiêu thụ.

- **Reconnect — ĐÃ CHỐT:** server KHÔNG replay buffer. Client (React) khi `onopen` (kể cả lần đầu) **refetch REST** (`GET /shipments` hoặc detail đang mở) rồi mới nghe delta. WS là kênh delta thuần, REST là nguồn sự thật — đơn giản, không state server-side per-connection.

### 6.1 [v0.9.12] Chính sách xử lý event phía frontend (normative — TASK-06 `ws.ts` tuân theo)

Chốt tường minh để `ws.ts` không phải tự đoán cách xử lý delta (dễ crash/lệch state):

1. **REST = nguồn sự thật, WS = delta.** State hiển thị luôn khởi từ REST fetch; WS chỉ cập nhật lên trên.
2. **Idempotent dispatch:** mọi event xử lý idempotent — nhận trùng cùng 1 event (VD reconnect trùng, server gửi lại) KHÔNG đổi kết quả (áp delta theo giá trị cuối, không cộng dồn).
3. **Unknown `type` → log + bỏ qua, KHÔNG crash** — server thêm `type` mới (version sau) không được làm vỡ client cũ.
4. **Reconnect backoff:** dùng exponential backoff (VD 1s → 2s → 4s → 8s → … cap **30s**), không reconnect dồn dập.
5. **Sau reconnect (kể cả lần `onopen` đầu):** **refetch list + detail đang mở** rồi mới nghe delta (nhất quán mục 6 "Reconnect").
6. **Event cho `shipment_id` KHÔNG có trong local state:** tùy loại — `position_update`/`eta_update`/`deviation_alert`/`tidal_alert`/`status_change`/`status_change_suggested`/`onboarding_update` → **bỏ qua** (chờ refetch đồng bộ); `proposal_created` (và lô mới xuất hiện) → **refetch list** để kéo lô/proposal mới về.
7. **Event đến TRƯỚC khi response REST về:** bỏ qua an toàn — refetch (điểm 5) sẽ đồng bộ lại state đúng; không cần buffer/replay phía client.

---

## 7. `.env` template hợp nhất — ĐÃ CHỐT tên biến

```bash
# ============ Core ============
DATABASE_URL=postgresql+asyncpg://app:app@db:5432/shipment_demo
REDIS_URL=redis://redis:6379/0                  # CHỈ Node dùng (BullMQ); Python không đọc
APP_PORT=1476                                    # khớp OAuth redirect URI đã đăng ký (§3.8)
APP_BASE_URL=http://localhost:1476               # production: https://domain-thật
DOMAIN=                                          # production only — Caddyfile dùng cho auto-TLS (để trống ở local)

# ============ LLM (OpenAI-compatible, §3.4) ============
LLM_BASE_URL=
LLM_API_KEY=
LLM_MODEL=

# ============ Nguồn dữ liệu ============
AISSTREAM_API_KEY=
AIS_MODE=live                                    # [v0.9.12] live | replay — replay đọc fixture JSON PositionReport
                                                 #   (backend/tests/fixtures/ais_positions.json) đi CÙNG đường xử lý upsert,
                                                 #   deterministic không cần key/tàu thật (test/CI/E2E TASK-17). Mặc định live.
STORMGLASS_API_KEY=                              # tide, 10 call/ngày (§6.2/§6.6)
SEARCH_API_PROVIDER=tavily                       # tavily — chốt 1, đổi được
SEARCH_API_KEY=
WPI_DATA_PATH=/app/data/wpi_ports.csv            # World Port Index tải offline 1 lần (§6.6).
                                                 # [v0.9.15] Khớp Docker: Dockerfile COPY backend/data/ → /app/data/;
                                                 #   file nguồn ở backend/data/wpi_ports.csv (TASK-07). Local test
                                                 #   resolve path tuyệt đối từ repo root, container dùng /app/data.
# Open-Meteo: không cần key (§6.2)

# ============ Auth (§3.8) ============
GOOGLE_CLIENT_ID=
GOOGLE_CLIENT_SECRET=
MICROSOFT_CLIENT_ID=
MICROSOFT_CLIENT_SECRET=
SESSION_JWT_SECRET=                              # ký JWT tự phát hành
SESSION_JWT_EXPIRE_HOURS=72
COOKIE_SECURE=false                              # true ở production HTTPS

# ============ Email Agent (§7.4) ============
DELEGATE_MAILBOX_IMAP_HOST=
DELEGATE_MAILBOX_USER=
DELEGATE_MAILBOX_PASSWORD=                       # app password IMAP
EMAIL_POLL_INTERVAL_MINUTES=5
# Allowlist (A) domain hãng tàu — comma-separated, ĐỔI KHÔNG CẦN SỬA CODE
# (theo yêu cầu: chỗ tinh chỉnh domain để config địa chỉ mail hãng tàu về sau;
#  giá trị dưới là placeholder 5 hãng demo — xác minh domain thật khi có mail thật)
CARRIER_EMAIL_DOMAINS=maersk.com,msc.com,one-line.com,wanhai.com,evergreen-line.com
# Allowlist (B) người forward nội bộ — comma-separated email đầy đủ
INTERNAL_FORWARDER_EMAILS=
# Whitelist người NHẬN auto-forward (§7.4 rào an toàn — không lấy từ nội dung mail)
AUTO_FORWARD_RECIPIENTS=

# ============ Hệ số ETA Engine (§6.3 — default trong code, override qua env) ============
SOG_MIN_KNOT=1.5                                 # guard 3b
ETA_DEVIATION_THRESHOLD_PCT=10                   # bước 11
CURRENT_AGAINST_THRESHOLD_KN=1.0                 # X
CURRENT_AGAINST_PENALTY_PCT=8                    # Y
WIND_AGAINST_THRESHOLD_KN=25                     # Z
WIND_AGAINST_PENALTY_PCT=5                       # W
AVG_SOG_WINDOW_MSGS=10                           # trượt 6-12 bản tin → chốt 10
ETA_RECOMPUTE_DEBOUNCE_SECONDS=60                # chống spam recompute theo nhịp AIS
ETA_HISTORY_MIN_DELTA_MINUTES=15                 # chỉ ghi history khi ETA dịch đủ lớn
ARRIVAL_RADIUS_KM=5                              # arrival detector (mục 0.3)
TIDAL_WINDOW_HOURS=2                             # ± quanh đỉnh triều coi là "trong cửa sổ"

# ============ Nhịp poll ============
WEATHER_POLL_HOURS=6                             # Open-Meteo (§6.2: 3-6h → chốt 6)
TIDE_POLL_HOURS=12                               # StormGlass (§6.2)
RESEARCH_CADENCE_HOURS=12                        # Agent A scheduled + research TTL (§6.3c/d)
TRAIL_SNAPSHOT_HOURS=6                           # vessel_trail (§3.1b)
AIS_RESUBSCRIBE_POLL_SECONDS=60                  # vòng an toàn nền (§3.1)

# ============ Node playwright-mcp (env riêng container đó — KHÔNG có DATABASE_URL, mục 0.1) ============
SCRAPE_REST_PORT=3000
MCP_SSE_PORT=3001
SCRAPE_CONCURRENCY=2
SCRAPE_JOB_TIMEOUT_SECONDS=90

# ============ Dev seed vessel — 1 tàu thật cho lô seed #1 (dev/test) ============
# LUỒNG THẬT (§6.7a): input người dùng CHỈ là vessel_name + voyage; IMO Resolver
# (TASK-11) tra ra IMO/MMSI. IMO/MMSI dưới đây là SHORTCUT tùy chọn, không phải input thật.
DEV_SEED_VESSEL_NAME=                            # BẮT BUỘC (nếu muốn seed tàu thật) — input luồng thật
DEV_SEED_VESSEL_VOYAGE=                          # BẮT BUỘC — input luồng thật
DEV_SEED_VESSEL_IMO=                             # 7 digits — TÙY CHỌN shortcut smoke AIS sớm (TASK-04 < TASK-11)
DEV_SEED_VESSEL_MMSI=                            # 9 digits — TÙY CHỌN shortcut
```

**Ghi chú:** toàn bộ hệ số có **default trong code** — `.env` chỉ cần điền nhóm secret/key. Giá trị hệ số đã chọn ghi vào phụ lục bài luận (§6.3). Không dùng bảng config DB ở MVP.

---

## 8. Danh sách hãng tàu demo — ĐÃ CHỐT (5 hãng)

| Hãng | Trang tra ETA (public, không login) | Domain mail (allowlist A — placeholder, config qua env) |
|---|---|---|
| Maersk | maersk.com/tracking (theo B/L hoặc container) | `maersk.com` |
| MSC | msc.com/en/track-a-shipment | `msc.com` |
| ONE | ecomm.one-line.com/one-ecom (public track) | `one-line.com` |
| Wan Hai | wanhai.com — Cargo Tracking | `wanhai.com` |
| Evergreen | shipmentlink.com — Cargo Tracking | `evergreen-line.com` |

- Carrier ETA Agent (§6.7b) nhắm chạy tốt với **ít nhất 3/5** hãng (spec nói "2-3 hãng demo" — 5 là danh sách ứng viên, không phải cam kết cả 5 scrape được; hãng nào chặn/khó thì fallback nhập tay đúng thiết kế).
- **Domain mail là placeholder [CẦN XÁC MINH]:** mail vận hành thật của hãng có thể đến từ subdomain/dạng khác (`notification.maersk.com`...). Vì vậy allowlist nằm ở `CARRIER_EMAIL_DOMAINS` (env, mục 7) — so khớp kiểu **suffix match** (`from_domain == d or from_domain.endswith("." + d)`) để `notification.maersk.com` vẫn qua với entry `maersk.com`. Khi demo bằng mail mô phỏng (§7.3), thêm domain/địa chỉ mail giả lập vào chính biến env này, không sửa code.
- Route thật + tàu thật cho từng hãng: điền lúc build (mục 13) — lịch tàu đổi theo tuần.

---

## 9. Chuẩn hóa dữ liệu — 2 hàm util dùng chung (module `normalize.py`)

Mọi module (CRUD, IMO Resolver client, Email Agent matcher, vessel_registry lookup) **bắt buộc** import từ đây — cấm tự cài lại:

```python
def normalize_vessel_name(raw: str) -> str:
    # trim → collapse whitespace về 1 space → upper
    # "  ever  Given " → "EVER GIVEN"
    # Áp ở: ghi/tra vessel_registry (§4.6), IMOResolverResult.vessel_name,
    #        so khớp new_vessel_name của rollover

def normalize_container_no(raw: str) -> str:
    # bỏ mọi khoảng trắng + gạch nối → upper → validate ISO 6346:
    #   ^[A-Z]{4}\d{7}$ + check-digit (ký tự thứ 11) đúng thuật toán ISO 6346
    # "csqu 305438-3" → "CSQU3054383"   (ví dụ chuẩn ISO 6346 — check-digit 3)
    # Sai format/check-digit → raise → API 400 INVALID_CONTAINER_NO;
    # Email Agent: container fail validation coi như "container lạ" (log, §7.1)
```

- **`route_key` (§6.3d):** UN/LOCODE thật, format `{POL}-{POD}` — VD `SGSIN-VNCLI`. Tra từ WPI dataset (có cột UN/LOCODE) + bảng alias thủ công trong config cho tên cảng demo (`"Cát Lái" → VNCLI`, `"Cat Lai" → VNCLI`, `"Singapore" → SGSIN`, `"Hong Kong" → HKHKG`, `"Kaohsiung" → TWKHH`). Không tra được → `route_key = NULL`, research vẫn chạy nhưng không cache (log warning).
- **`imo`/`mmsi`:** TEXT, giữ nguyên leading zero. IMO đúng 7 digits, MMSI đúng 9 digits (regex ở Pydantic mục 4). Không lưu số nguyên.

---

## 10. Auth / session contract chi tiết

- **JWT claims (tự phát hành, §3.8 bước 6):**
  ```json
  { "sub": "<users.id>", "role": "user|admin", "iat": ..., "exp": ... }
  ```
  `exp` = iat + `SESSION_JWT_EXPIRE_HOURS` (72h). HS256, secret = `SESSION_JWT_SECRET`. Không refresh token ở MVP — hết hạn thì login lại (ghi giới hạn §9 spec: chưa revoke-list).
- **Cookie JWT:** tên `session_token`, `Path=/`, `Max-Age=259200` (=72h), `HttpOnly; SameSite=Lax`, `Secure` theo env — đúng §3.8(B). Cookie handshake do SessionMiddleware tự quản (tên mặc định, không cần chốt).
- **Middleware:** dependency FastAPI `get_current_user` — đọc cookie → verify → nạp `users` → gắn `request.state.user`. Thiếu/sai/hết hạn → 401 `UNAUTHENTICATED` (JSON, mục 3.1 — không redirect). Route cần admin (chưa có ở MVP, chừa sẵn) → 403 `FORBIDDEN`.
- **Sau callback:** redirect 302 về `/` (SPA shell công khai — khớp phân tích §3.8(B): tránh đáp thẳng vào route bảo vệ trong chuỗi navigation cross-site).
- **`GET /auth/me`:** shape ở mục 3.2 — SPA gọi lúc mount để render tên/role + quyết định show màn login.

---

## 11. REST error envelope

Đã chốt ở mục 3.1 (gộp để tránh lặp): FastAPI-native `{"detail": {"code", "message"}}`, 422 giữ nguyên shape Pydantic mặc định, danh mục code ở 3.1.

---

## 12. Docker network — hostname/port nội bộ

| Service (= hostname trong compose network) | Image | Port nội bộ | Expose ra host? |
|---|---|---|---|
| `caddy` | caddy:2 | 80/443 | **Duy nhất expose** (production). Local dev không chạy caddy |
| `webapp` | build (Python 3.12) | **1476** | Local dev: map `1476:1476` (khớp OAuth redirect). Production: không expose, caddy proxy tới `webapp:1476` |
| `playwright-mcp` | build từ `mcr.microsoft.com/playwright` | REST **3000**, MCP SSE **3001** | Không |
| `db` | postgres:16-alpine | 5432 | Không (dev có thể map 5432 để debug — tùy chọn) |
| `redis` | redis:7-alpine | 6379 | Không |

- URL nội bộ Python gọi Node: `http://playwright-mcp:3000/scrape-jobs` (REST) và `http://playwright-mcp:3001/sse` (MCP transport — path cụ thể chốt theo version `@playwright/mcp` đã pin, spec §3.6 để version-agnostic).
- 2 cửa **tách port** (3000/3001) thay vì chung — process Express và process MCP server độc lập trong cùng container, đỡ multiplex path.
- Env riêng từng container: `playwright-mcp` nhận `REDIS_URL`, `SCRAPE_*` — **KHÔNG nhận `DATABASE_URL`** (mục 0.1). `webapp` nhận tất cả trừ `SCRAPE_REST_PORT`/`MCP_SSE_PORT` (biết qua URL trên).

---

## 13. Seed data — 4 lô + 2 user

Nguyên tắc: phủ đủ 3 nhánh nghiệp vụ (import auto_email, import manual, export auto_email) + 1 cặp trùng tên tàu. **Tên tàu/voyage/IMO thật đánh dấu `[ĐIỀN LÚC BUILD]`** — tàu chạy tuyến đổi theo tuần, điền cứng bây giờ là vô nghĩa; cấu trúc dưới là hợp đồng, giá trị điền sau bằng cách tra lịch tàu thật tại thời điểm build (VesselFinder/website hãng).

> **[v0.9.12] Ba MỤC TIÊU seed phân biệt tường minh** (trước đây gộp — nay tách rõ nhánh nào phục vụ mục tiêu nào; **giữ nguyên 4 lô / 4 nhánh cấu hình lô #1 dưới**, chỉ nhóm lại theo mục tiêu):
> - **(a) Offline-deterministic seed** — luôn chạy được, KHÔNG cần key/tàu thật; phục vụ test/CI/**TASK-17 E2E**. Chạy với `AIS_MODE=replay` (IC§7) + fixture `ais_positions.json`. Ứng với **nhánh (d)** dưới (thiếu cả `DEV_SEED_VESSEL_NAME` → 4 lô placeholder tĩnh `resolved`, IMO/MMSI placeholder khớp MMSI trong fixture replay).
> - **(b) Live-integration seed** — dùng `DEV_SEED_VESSEL_*` + key thật (AIS live) để smoke I/O thật. Ứng với **nhánh (b)** dưới (NAME+VOYAGE + THÊM IMO/MMSI → lô #1 `resolved`, AIS live bám ngay) và **nhánh (c)** (chỉ NAME+VOYAGE → lô #1 `pending`, chờ IMO Resolver TASK-11 tra rồi AIS live bám — đúng luồng thật nhất).
> - **(c) Demo seed** — cập nhật tàu thật + tuyến thật ngay TRƯỚC ngày demo (lịch tàu đổi theo tuần); điền `[ĐIỀN LÚC BUILD]` bằng giá trị thật tại thời điểm đó.
>
> Ba mục tiêu KHÔNG loại trừ nhau — cùng một seed script, khác `.env` (chủ yếu `AIS_MODE` + `DEV_SEED_VESSEL_*`). Mục tiêu (a) là mặc định an toàn khi không có gì; (b)/(c) bật thêm khi có key/tàu thật.

| # | direction | incoterm | mode (derived) | carrier | vessel_name | voyage | pol | pod | container_no |
|---|---|---|---|---|---|---|---|---|---|
| 1 | import | FOB | `auto_email` | Maersk | `[ĐIỀN LÚC BUILD — tàu X]` | `[V.001N]` | SGSIN Singapore | VNCLI Cát Lái | `[hợp lệ ISO 6346]` |
| 2 | import | CIF | `manual` | MSC | `[ĐIỀN LÚC BUILD]` | `[...]` | HKHKG Hong Kong | VNCLI Cát Lái | `[...]` |
| 3 | **export** | CIF | `auto_email` | ONE | `[ĐIỀN LÚC BUILD]` | `[...]` | VNCLI Cát Lái | SGSIN Singapore | `[...]` |
| 4 | import | FOB | `auto_email` | Wan Hai | `[ĐIỀN LÚC BUILD — **cùng tên tàu lô 1, khác voyage**]` | `[V.002S]` | TWKHH Kaohsiung | VNCLI Cát Lái | `[...]` |

- Lô 1+4 **cố ý cùng `vessel_name`, khác `voyage_no`** — test case trùng tên tàu (§9 spec, §4.6). Nếu lúc build không tìm được cặp tàu thật trùng tên đang chạy đúng 2 tuyến, hạ yêu cầu: seed lô 4 bằng tên tàu của lô 1 + voyage giả, chỉ để test nhánh lọc voyage của IMO Resolver (lô 4 chấp nhận `manual_required` khi demo tracking thật).
- Mỗi lô seed: 1 dòng `shipment_legs` (leg_no=1, is_active_leg=true). **Riêng lô #1 (dev vessel từ mục 7):**
  - Có `DEV_SEED_VESSEL_NAME` + `DEV_SEED_VESSEL_VOYAGE` → dùng làm `vessel_name`/`voyage_no` lô #1 (input luồng thật). 3 lô còn lại giữ placeholder tĩnh.
  - **Có THÊM** cả `DEV_SEED_VESSEL_IMO` + `DEV_SEED_VESSEL_MMSI` → lô #1 seed sẵn `resolved` (`imo_resolved_via='manual'`, IMO/MMSI đã điền) — shortcut để AIS worker (TASK-04) thấy vị trí realtime ngay dù chưa có IMO Resolver.
  - **Thiếu IMO/MMSI** (chỉ có NAME+VOYAGE) → lô #1 seed `onboarding_status='pending'`, IMO/MMSI NULL — đúng luồng thật, chờ IMO Resolver (TASK-11) tra ra rồi AIS mới bám. Đây là trạng thái đúng nhất về nghiệp vụ.
  - **Thiếu cả NAME** → 4 lô đều placeholder tĩnh (điền IMO/MMSI placeholder + `resolved` để 3 lô còn lại chạy tracking khi có tàu thật, như §8 bước 2).
- `status='on_sea'`, `atd` = thời điểm khởi hành thật của chuyến đã chọn, `eta_original` từ lịch hãng (`eta_original_source='manual'`).
- **User seed:** `admin@demo` (role `admin`, provider `google`, `provider_sub` = sub thật của tài khoản Google bạn dùng test — điền sau lần login đầu) + `user@demo` (role `user`). Seed script cho phép chạy lại (upsert theo `(provider, provider_sub)`).

---

## 14. Email mẫu test (§7.3) — 4 mail, dùng được ngay

Biến `{VESSEL_A}`, `{CONT_1}`... khớp giá trị seed mục 13 lúc build. Gửi vào mailbox delegate từ địa chỉ nằm trong allowlist tương ứng (mail 1-3: domain hãng — khi demo mô phỏng, thêm domain giả lập vào `CARRIER_EMAIL_DOMAINS`; mail 4: từ địa chỉ trong `INTERNAL_FORWARDER_EMAILS` — test đường manual-forward của lô 2).

**Mail 1 — Rollover Notification (có tên tàu mới → test chuỗi §6.8d đầy đủ):**
```
Subject: Rollover Notification - B/L {BL_1} - {CONT_1}
Dear Customer,
Please be advised that due to vessel space constraints, the below shipment
has been rolled over to the next available vessel:
  B/L Number: {BL_1}
  Container: {CONT_1}
  Original Vessel/Voyage: {VESSEL_A} / {VOY_1}
  New Vessel/Voyage: {VESSEL_B} / {VOY_1B}
  Revised ETA {POD_1}: {NEW_ETA_ISO}
We apologize for the inconvenience.
{CARRIER_1} Customer Service
```
Kỳ vọng: `EmailExtraction(containers=[{CONT_1}], from_voyage={VOY_1}, to_voyage={VOY_1B}, new_eta=..., new_vessel_name={VESSEL_B}, email_type="rollover")` → 1 proposal → approve → `resolve_and_activate_leg()`.

**Mail 2 — Vessel Delay Notice (chỉ dời ETA, không đổi tàu):**
```
Subject: Vessel Delay Advisory - {VESSEL_C} Voyage {VOY_3}
Dear Valued Customer,
Vessel {VESSEL_C} voyage {VOY_3} is experiencing a delay due to port congestion
at transshipment hub. Revised ETA {POD_3}: {NEW_ETA_ISO} (previously {OLD_ETA_ISO}).
Affected container: {CONT_3}.
{CARRIER_3} Notification Service
```
Kỳ vọng: `new_vessel_name=None`, `email_type="transit_delay"` → approve chỉ update `eta_current` + `eta_history(source='email_agent')`, KHÔNG đụng leg.

**Mail 3 — Nhiều container, có 1 container lạ (test case §7.1 v0.9.6 — bắt buộc):**
```
Subject: Schedule Change - Multiple Units
Dear Customer,
The following units on {VESSEL_A} / {VOY_1} are affected by schedule change,
revised ETA {POD_1}: {NEW_ETA_ISO}:
  1. {CONT_1}
  2. ZZZU9999992          ← không tồn tại trong hệ thống. LƯU Ý: số này PHẢI pass
                            check-digit ISO 6346 (tính lại lúc build bằng chính
                            normalize_container_no) — nếu fail check-digit nó rơi nhánh
                            validation, KHÔNG test được nhánh "container lạ" §7.1
  3. {CONT_4}
{CARRIER_1} Customer Service
```
Kỳ vọng: 2 proposal (cont 1 + 4), container lạ → `processed_emails.unmatched_containers` (log, không proposal, không chặn 2 cont khớp).

**Mail 4 — Forward tay cho lô `manual` (test allowlist B):** lấy nội dung dạng Mail 2 (đổi biến sang lô 2), gửi từ địa chỉ nhân viên trong `INTERNAL_FORWARDER_EMAILS` theo kiểu Gmail true-forward. Kỳ vọng: Agent vẫn đọc + tạo proposal (monitoring_mode KHÔNG gate đọc, §7.1) — chỉ khác là không auto-forward.

**Format thật từ U&I [CẦN XÁC MINH]:** khi xin được mail thật, thay 4 mẫu trên bằng format thật — cấu trúc extraction không đổi.

---

## 15. Timezone / datetime convention

- **DB:** mọi cột `timestamptz`, giá trị luôn UTC. Python chỉ tạo `datetime.now(timezone.utc)` — cấm naive datetime (Pydantic validator từ chối).
- **API:** serialize ISO8601 với suffix `Z` (`2026-07-17T09:30:00Z`).
- **Frontend:** convert sang timezone **trình duyệt** khi hiển thị (dayjs/Intl). Không gửi kèm bản local từ backend.
- **Giới hạn ghi nhận (nêu khi bảo vệ):** giờ triều/ETA của cảng nước ngoài (POD lô xuất) cũng hiển thị theo giờ trình duyệt (giờ VN), KHÔNG theo giờ địa phương cảng — chấp nhận ở MVP vì người dùng là nhân viên U&I tại VN; hiển thị giờ địa phương cảng ghi future work.
- **Tính toán ETA/deviation:** toàn bộ bằng epoch/UTC — timezone chỉ là chuyện hiển thị.

---

## 16. Ma trận "task nào cần mục nào" (dùng khi viết plan)

| Task (theo §8 spec) | Mục contract phải đọc |
|---|---|
| 1. Spike AIS + Open-Meteo | 7 (env), 15 |
| 2. DB + model + seed | 0.2, 1, 2, 9, 13 |
| 3. CRUD lô hàng | 1.1 (derive), 3, 4.4, 9, 11 |
| 4. AIS worker | 0.3, 6, 7 (nhịp), 2.3 (query resolved) |
| 5. ETA engine | 0.2 (env_conditions), 5.1 (recompute contract), 7 (hệ số) |
| 6. Frontend + WS | 1.2 (milestone map), 3, 6, 10 (auth/me), 15 |
| 7. Weather/Tide poll | 0.2, 7, 9 (route_key/WPI) |
| 8. Agent A | 5, 4.3 |
| 9. Agent B + cache | 5.2, 4.3, 0.2 (cache = findings) |
| 10. Container playwright-mcp + queue | 0.1, 3.3, 12 |
| 11. IMO Resolver | 3.3, 4.1, 9 |
| 12. Carrier ETA Agent | 3.3 (cửa MCP), 12 |
| 13. Email Agent | 0.2 (processed_emails), 4.2, 8, 9, 14 |
| 14. Auth OAuth | 3.2 (/auth/*), 10 |
| 15. docker-compose + deploy | 7, 12 |
| 16. Auto-forward [STRETCH] | 7 (AUTO_FORWARD_RECIPIENTS), 8 |
| 17. E2E offline deterministic | 7 (`AIS_MODE`), 13 (offline seed), 15 (UTC), 6 (WS delta) |

> **Phạm vi ma trận:** gồm TASK-00..17. Transit `switch_active_leg`/tín hiệu kép §6.8c và cleanup §4.9 vẫn là STRETCH ngoài 18 task hiện tại; khi build, thêm TASK-18+ và contract cadence tương ứng.
