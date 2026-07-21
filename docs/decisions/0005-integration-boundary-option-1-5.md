# Decision Record

## Decision ID

0005-integration-boundary-option-1-5

## Date

2026-07-21

## Status

accepted

## Context

Hệ nói chuyện với rất nhiều external system (aisstream, Open-Meteo, StormGlass,
Tavily, LLM endpoint, AG2, Playwright MCP, IMAP), trong đó nhiều package
experimental đổi API giữa version. Cần một mức abstraction đủ để cô lập rủi ro
nhưng không rơi vào over-engineering kiểu hexagonal đầy đủ cho một demo PoC.

## Options Considered

1. **"Option 1.5" — nguyên tắc nhẹ, có kỷ luật** — công thức 3 mảnh cho mỗi
   integration, cấm abstraction thừa. Pros: cô lập đúng chỗ rủi ro, chi phí
   thấp. Cons: đòi kỷ luật review thay vì kiến trúc ép buộc.
2. **Full hexagonal (ports & adapters mọi nơi)** — Pros: sạch tuyệt đối.
   Cons: quá nặng cho demo, mỗi service thêm 2-3 tầng gián tiếp. **Bị loại.**
3. **Không boundary** — gọi httpx/SDK thẳng trong domain — Pros: nhanh nhất.
   Cons: framework experimental chảy vào domain, đổi version là sửa khắp nơi.
   **Bị loại.**

## Decision

Chốt "Option 1.5" (v0.9.12):

- **Công thức 3 mảnh** cho mỗi external integration: (1) internal typed model
  Pydantic ngay tại boundary — không để dict provider chảy vào domain;
  (2) client function/class nhỏ gom URL/parse/HTTP status; (3) error mapping
  thống nhất — mọi exception SDK/HTTP → `ExternalIntegrationError` kèm cờ
  `retryable: bool`.
- **CẤM Interface/Protocol/Factory** trừ khi có ≥2 implementation HOẶC cần cho
  replay mode. `AisSource` là ngoại lệ hợp lệ (live + replay).
- **3 nhóm boundary:** (1) adapter riêng cho nguồn rủi ro cao/experimental/
  stateful: StormGlass, Tavily, LLM (`LLMClient`), AG2 (`AG2Runner`),
  MCP/Playwright (`BrowserAgentClient`), IMAP (`imap_client`); (2) client cực
  mỏng không Interface: Open-Meteo (HTTP đơn giản, không key, 1 chỗ dùng);
  (3) TUYỆT ĐỐI không adapter-hóa domain nội bộ (`eta_engine`, `leg_service`,
  `proposal_service`).
- **2 nguyên tắc thép:** (a) mọi I/O ngoài (HTTP/WS/IMAP/SDK) nằm trong
  `integrations/` hoặc client riêng — domain service CẤM import trực tiếp
  httpx/aiohttp/SDK; (b) adapter chỉ lo transport/auth/parsing/timeout-retry/
  error-mapping — CẤM chứa business logic / DB transaction / broadcast event.

## Consequences

**Positive:**

- Framework experimental (AG2, MCP) bị nhốt sau 1 file mỗi loại — đổi version
  chỉ sửa 1 chỗ.
- Domain test offline được vì không phụ thuộc SDK thật.
- Error handling đồng nhất qua `ExternalIntegrationError.retryable`.

**Tradeoffs:**

- Ranh giới dựa trên kỷ luật review (import check), không có compiler ép.
- Một số call đơn giản (Open-Meteo) vẫn phải đi qua client mỏng thay vì gọi
  inline.

## Related Stories

- `docs/stories/TASK-12-carrier-eta-agent/` (`BrowserAgentClient` gateway MCP)
- `docs/stories/TASK-13-email-agent/` (`imap_client` transport-only)
- `docs/stories/TASK-11-imo-resolver-resolve-leg/` (`scrape_client` + typed `IMOResolverResult`)
