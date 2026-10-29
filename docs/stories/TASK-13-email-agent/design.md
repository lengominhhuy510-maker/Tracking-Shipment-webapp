# TASK-13 — Email Agent (Module 2): Design

## Status

planned

## Lane

high-risk

## Ranh giới module (Option 1.5 — Ràng buộc toàn cục v0.9.12)

| Layer | File | Trách nhiệm |
|---|---|---|
| Transport | `backend/app/integrations/imap_client.py` | IMAP connect/auth/fetch UNSEEN theo UID/STORE `\Seen`/timeout/error mapping → `ExternalIntegrationError(retryable)`. KHÔNG business, KHÔNG DB. |
| Extraction | `backend/app/agents/email_agent.py` | LLM extract `EmailExtraction` (IC§4.2) qua `LLMClient` (TASK-08). JSON mode + validate Pydantic + retry đúng 1 lần; fail sau retry → outcome `parse_failed`. Parse xuyên lớp forward nếu là true-forward (§7.4). |
| Business | `backend/app/services/email_service.py` | Allowlist, dedup, match container, tạo proposal, ghi `processed_emails`, điều phối thứ tự commit/`\Seen`. |
| Decision | `backend/app/services/proposal_service.py` | approve/reject + rollover chain. |
| Leg | `backend/app/services/leg_service.py` (MODIFY) | Thêm `resolve_and_activate_leg(session, new_leg_id, imo, mmsi, resolved_via)` — session-first, cùng khuôn `resolve_leg`. |
| API | `backend/app/api/proposals.py` | `GET /agent-proposals`, `POST /{id}/approve|reject` (IC§3.2). |

Domain service CẤM import imaplib/httpx trực tiếp — mọi I/O qua client (nguyên tắc thép Option 1.5).

## Flow poll (§7.1)

1. Poller (duy nhất, lifespan) mỗi `EMAIL_POLL_INTERVAL_MINUTES`: fetch mail UNSEEN qua `imap_client`.
2. Mỗi mail: check dedup `processed_emails.message_id` → đã có thì skip (chỉ retry `\Seen` nếu `seen_set_at` NULL).
3. Allowlist KÉP §7.4: from_domain suffix-match `CARRIER_EMAIL_DOMAINS` (A) HOẶC from-address thuộc `INTERNAL_FORWARDER_EMAILS` (B) — fail → outcome `rejected_allowlist`. Suffix-match theo IC§8: `from_domain == d or from_domain.endswith("." + d)`.
4. Đọc mọi mail hợp lệ **bất kể monitoring_mode** (§7.1 — mode chỉ gate auto-forward TASK-16, không gate đọc).
5. LLM extract → `EmailExtraction`; container qua `normalize_container_no` (IC§9), fail check-digit = "container lạ" → `unmatched_containers` (log, không proposal, không chặn container khớp).
6. Match container → tạo 1 proposal/container khớp; `extracted_json` lưu nguyên `EmailExtraction.model_dump_json()` (IC§4.2). Idempotency: unique `(source_email_id, shipment_id)`.
7. Ghi `processed_emails` với outcome ∈ {`proposals_created`, `no_match`, `rejected_allowlist`, `parse_failed`} — đúng 4, KHÔNG thêm `partial_match`.
8. `broadcast_proposal_created` (import từ `app.services.broadcast` — TASK-04 bước 0).

## Thứ tự giao dịch — commit `processed_emails` TRƯỚC STORE `\Seen` (Patch p2)

Quyết định chốt trong Spec §13, phân tích 2 chiều fail:

- **`\Seen` trước, DB insert fail:** mail đã Seen nhưng `processed_emails` chưa có → poll UNSEEN kế KHÔNG thấy lại → **mất mail vĩnh viễn**. → CẤM thứ tự này.
- **DB trước (chốt), `STORE \Seen` fail** (mạng rớt giữa chừng): poll kế fetch lại mail unseen → dedup `message_id` skip ngay (không xử lý lại), `seen_set_at` vẫn NULL → retry `STORE \Seen` ở cuối poll hoặc job nền. Không mất mail, không double-proposal.

3 cột trace `imap_uid`/`imap_folder`/`seen_set_at` (IC§0.2, Patch p2) phục vụ đúng nhánh retry này.

**Tiền đề mailbox delegate (§7.2):** mailbox DÀNH RIÊNG, không ai đọc web UI → `\Seen` chỉ do agent set. Nếu mailbox thành dùng chung → DỪNG đánh giá lại (xem execplan stop conditions).

## Rollover chain (§6.8d)

`approve(proposal_id, user_id)` khi `new_vessel_name` không NULL:

1. `scrape_client.resolve_imo(new_vessel_name, ...)` (TASK-11) tra tàu mới.
2. INSERT `shipment_legs` mới **CÙNG `leg_no`** với leg hiện tại; set `superseded_at` dòng cũ.
3. `resolve_and_activate_leg(session, new_leg_id, imo, mmsi, resolved_via)` — `is_active_leg` chuyển NGAY (partial unique index `uq_legs_one_active` ép 1 active/lô), mirror lên `shipments`, bắn `ResubscribeSignal` + `broadcast_onboarding_update`. Pseudo-code: §6.8d.

Approve có `new_eta` → update `eta_current` + INSERT `eta_history(source='email_agent')`. Đã decided → **409**. `reject(proposal_id, user_id, reason)` tương tự về guard 409.

## Contract tham chiếu (KHÔNG copy — đọc tại nguồn)

- `EmailExtraction` shape: **IC§4.2** (`containers[]` min 1, `new_vessel_name`, `email_type`).
- Allowlist/suffix-match + 5 hãng demo: **IC§8**, **§7.4**.
- `processed_emails` DDL + 3 cột trace: **IC§0.2** / IC§2.2.
- 4 mail mẫu fixture: **IC§14**.
- Normalize: **IC§9** — import từ `normalize.py`, cấm cài lại.
