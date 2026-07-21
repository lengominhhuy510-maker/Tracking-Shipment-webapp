# Decision Record

## Decision ID

0006-dependency-pinning-lock-reproducibility

## Date

2026-07-21

## Status

accepted

## Context

Nhiều package lõi của dự án còn experimental (AG2, `@playwright/mcp`, MCP
Python SDK) và đổi API giữa các version. Worker agent lại có xu hướng "bịa"
tham số theo bản latest trong training data. Nếu version trôi giữa các task,
build không lặp lại được và code viết theo API của bản khác bản đang cài.

## Options Considered

1. **Pin exact gói experimental + lock reproducibility** — Pros: build lặp lại
   được, worker đọc docstring đúng bản đang cài, gate 1 lần dùng nhiều lần.
   Cons: nâng version là việc chủ động, phải qua gate lại.
2. **Pin latest / floating (`^`, `>=` cho tất cả)** — Pros: luôn mới. Cons: API
   experimental đổi giữa version → build không lặp lại được, code gãy ngẫu
   nhiên theo ngày cài. **Bị loại.**

## Decision

- **Gói experimental pin EXACT** theo bảng chốt v0.9.16 (tra registry
  2026-07-21): `@playwright/mcp` = **0.0.78** (npm); `ag2` = **0.14.0** (hoặc
  nhánh gói `autogen` = **0.14.1** — chọn 1 tên cài được rồi pin exact);
  `authlib` = **1.7.2**; `python-jose[cryptography]` = **3.5.0**;
  `mcp` = **1.12.4** (MCP Python SDK).
- **Gate tại TASK-01** (compatibility spike `spike_ag2.py`/`spike_mcp.py`) —
  các task sau (TASK-08/09/10/12/14) **DÙNG LẠI bản đã gate, KHÔNG tự bump,
  KHÔNG thêm mới**.
- Gói stable (fastapi, sqlalchemy, uvicorn...) dùng **`>=` floor**.
- Worker **đọc docstring/signature bản ĐÃ PIN** trước khi dùng — không bịa API
  theo bản latest.
- **Lock reproducibility (1 quy tắc cho 2 ecosystem):** task nào thật sự
  MODIFY `backend/requirements.txt` PHẢI khai + regenerate + commit
  `requirements.lock.txt` (`pip freeze`); task nào MODIFY
  `frontend/package.json` hoặc `playwright-mcp/package.json` PHẢI regenerate +
  commit `package-lock.json` tương ứng; `npm ci` chỉ chạy với lock đã commit.

## Consequences

**Positive:**

- Build reproducible từ clone sạch (lock đã commit + `npm ci`).
- API experimental được "đóng băng" đúng bản đã spike thành công — code các
  task sau viết theo đúng docstring bản đó.
- Diff lock file trong commit làm bằng chứng dependency thay đổi ở task nào.

**Tradeoffs:**

- Không nhận bug fix mới của gói experimental cho tới khi chủ động re-gate.
- Mỗi lần đụng file dependency phải nhớ regenerate lock — quên là vi phạm
  scope check.

## Related Stories

- `docs/stories/TASK-10-scrape-infra-playwright-mcp/` (`@playwright/mcp@0.0.78`, không bump)
- `docs/stories/TASK-12-carrier-eta-agent/` (`mcp==1.12.4` + AG2 đã gate)
- `docs/stories/TASK-14-auth-oauth-jwt/` (`authlib`/`python-jose` pin sẵn, mặc định không MODIFY requirements)
- `docs/stories/TASK-02-db-schema-migration-seed/` (dùng stack đã pin, không thêm dependency)
