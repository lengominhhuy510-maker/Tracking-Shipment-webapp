# Decision Record

## Decision ID

0003-single-process-embedded-workers

## Date

2026-07-21

## Status

accepted

## Context

Backend cần nhiều background task chạy dài: AIS worker (WebSocket long-running),
weather/tide poll, trail snapshot, scheduler Agent A, email poller. Một số state
nằm in-memory (ResubscribeSignal `asyncio.Event`, mốc thời gian arrival
detector, đếm quota StormGlass). Nếu chạy nhiều uvicorn worker, mỗi process sẽ
có bản copy state riêng và nhiều poller trùng nhau (double-poll IMAP, double
subscribe AIS).

## Options Considered

1. **Đúng 1 uvicorn worker, background embedded qua lifespan** — Pros: state
   in-memory an toàn (1 process ghi), không cần external queue/locking cho
   background nội bộ, deploy đơn giản. Cons: không scale ngang, 1 process chết
   là mất hết.
2. **Multi-worker + external queue** (Celery/ARQ...) cho background — Pros:
   scale, isolation. Cons: thừa cho PoC 3-5 lô hàng, phá in-memory state, thêm
   hạ tầng phải vận hành. **Bị loại.**

## Decision

Chọn Option 1:

- Chạy **đúng 1 uvicorn worker** (`CMD uvicorn app.main:app --port 1476`,
  KHÔNG `--workers >1` — comment cứng trong `backend/Dockerfile`).
- Mọi background task (AIS worker, weather/tide poll, trail snapshot, scheduler
  Agent A, email poller) khởi động embedded qua **lifespan startup**
  (`asyncio.create_task`), shutdown hủy task sạch.
- Chỉ 1 email poller được lifespan khởi động; multi-poller cần locking là
  Known Limitation, không thêm advisory lock cho MVP.
- Ngoại lệ duy nhất: scrape concurrency do BullMQ phía Node quản (xem
  [[0002-language-boundary-python-node]]).

## Consequences

**Positive:**

- State in-memory (resubscribe event, arrival detector, quota counter) đúng
  đắn mà không cần Redis/lock phía Python.
- Không có double-poll IMAP / double-subscribe AIS.
- Deploy = 1 container webapp, hợp quy mô demo 3-5 lô.

**Tradeoffs:**

- Không scale ngang; throughput giới hạn 1 process (chấp nhận cho PoC).
- Task background lỗi nặng có thể ảnh hưởng event loop chung — mọi feature I/O
  phải fallback êm, không crash app (ràng buộc error handling toàn cục).

## Related Stories

- `docs/stories/TASK-13-email-agent/` (single poller trong lifespan)
- `docs/stories/TASK-10-scrape-infra-playwright-mcp/` (concurrency thuộc Node/BullMQ)
