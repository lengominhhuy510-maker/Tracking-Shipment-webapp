# Architecture

> **This file is required by Harness. Fill it in before running `/harness-intake`
> on real work.** Agents read this document before changing code, so the more
> accurate it is, the safer their changes will be.
>
> **Nguồn chân lý:** `idea.md` (index) → `Spec_Demo_GiamSatLoHang-v0_9_19.md`
> (quyết định) + `Interface-Contract_v0.9.9.md` (hình dạng interface). File này
> chỉ tóm tắt để agent định hướng — mọi chi tiết chính xác (schema, endpoint,
> signature, env) tra ở Spec/IC. **Quy tắc đọc:** active section là normative;
> changelog / `[v0.x]` / historical wording / Known Limitations chỉ để giải
> thích; khi mâu thuẫn, active thắng.

## Overview

Hệ thống hỗ trợ giám sát lô hàng nhập + xuất cho bộ phận Kinh Doanh (U&I
Logistics): gom dữ liệu rải rác (vị trí tàu AIS, thời tiết/dòng chảy, thủy triều,
email hãng tàu) về một chỗ và biến thành cảnh báo ETA chủ động — chuyển CSKH sau
bán từ *bị động* (khách hỏi mới tra) sang *chủ động* (hệ tự cập nhật hành trình +
cảnh báo sớm khi ETA biến động). Đây là **add-on layer**, KHÔNG thay thế TMS/hệ
hãng tàu. Phạm vi là proof-of-concept (MVP): ~3-5 lô đồng thời, hai tuyến ngắn
(nhập về Cát Lái; xuất C/D từ Cát Lái đi cảng khu vực).

Mọi con số ETA do **công thức rule-based** sinh ra — KHÔNG train/fine-tune ML;
LLM chỉ điều phối + diễn giải.

## Components

Trình bày theo 4 layer (Spec §3):

- **Layer 4 — Frontend** (React + Vite + Leaflet): danh sách lô (dạng đơn hàng
  TMĐT), chi tiết lô với progress bar milestone + bản đồ tàu, ô "nhận định
  chuyên gia", tín hiệu research "cần xác minh", hộp đề xuất chờ duyệt. Nhận
  update qua REST + WebSocket. Build tĩnh → `dist/` (KHÔNG container riêng).
- **Layer 3 — AG2 Multi-Agent** (LLM qua endpoint OpenAI-compatible):
  - **Agent A — ETA Reasoning:** điều phối, gọi tool Layer 2, tổng hợp nhận định
    chuyên gia. KHÔNG tự quyết ETA baseline chính thức.
  - **Agent B — Research:** web search → đánh giá → kết luận; trả Pydantic
    (`event, relevance, route_impact, confidence, sources`). Có vòng phản hồi
    thật A↔B. Chỉ chạy khi `onboarding_status = resolved`.
  - **Onboarding (1 lần/lô):** (a) **IMO Resolver** — script Playwright cứng,
    KHÔNG LLM, tra IMO/MMSI từ VesselFinder qua REST `/scrape-jobs`; (b)
    **Carrier ETA Agent** — agentic qua Playwright MCP (mỗi hãng 1 layout), qua
    MCP transport riêng.
  - **Email Agent (Module 2):** tách riêng, không nằm trong hội thoại A↔B; nối
    qua DB (`agent_proposals`). Đọc mailbox delegate, LLM trích xuất thông báo
    rớt tàu/đổi lịch, tạo proposal — human-in-the-loop duyệt.
- **Layer 2 — Tool tính toán** (FastAPI, chạy embedded):
  - **AIS Worker:** tiến trình nền giữ WebSocket sống (aisstream.io), upsert vị
    trí realtime + ghi trail lấy mẫu. Hỗ trợ `AIS_MODE=live|replay`.
  - **Weather/Wave/Current poll** (Open-Meteo, không key) + **Tide poll**
    (StormGlass).
  - **ETA Engine** 2 tầng rule-based (Tầng 1 động học, Tầng 2 điều chỉnh theo
    gió/dòng chảy).
- **Layer 1 — DB** (PostgreSQL): 10 bảng thực thi = 8 bảng nghiệp vụ (§4) +
  `env_conditions` + `processed_emails` (IC§0.2).
- **playwright-mcp** (container Node riêng): REST nhỏ (Express) + BullMQ worker +
  Chromium + `@playwright/mcp`. **KHÔNG có `DATABASE_URL`** — Node không chạm
  Postgres (IC§0.1).
- **Redis:** job queue cho BullMQ (playwright-mcp). Python KHÔNG chạm Redis.

## Data Flow

**Vòng đời lô hàng + realtime:**

1. **Nhập lô** → REST `POST /shipments` (B/L + container + Incoterm +
   vessel/voyage). `derive_monitoring_mode(direction, incoterm)` quyết
   `auto_email | manual`; export×E/F → raise (400).
2. **Onboarding** (`onboarding_status: pending → resolved | manual_required`):
   Python đẩy job → `playwright-mcp` → IMO Resolver tra IMO/MMSI (REST) và
   Carrier ETA Agent tra ETA baseline (MCP). Python poll `GET /scrape-jobs/{id}`,
   validate Pydantic, tự ghi `vessel_registry` và gọi `resolve_leg()` (1
   transaction, Python-only).
3. **AIS realtime:** worker subscribe MMSI của lô `resolved` chưa
   `arrived/delivered`; mỗi bản tin → upsert `shipments.current_*` → ETA Engine
   tính lại → nếu vượt ngưỡng đẩy cảnh báo qua WebSocket. Trail ghi mẫu ≥6h/điểm,
   tối đa 12 điểm/lô.
4. **Chuyển status** (IC§0.3): `new→on_sea` khi user nhập `atd`; `on_sea→arrived`
   hệ đề xuất (bán kính POD + SOG thấp ≥30 phút) → người xác nhận;
   `arrived→delivered` thủ công.
5. **Email Agent** (poll định kỳ): đọc mailbox → allowlist gate → LLM extract →
   tạo `agent_proposals` (dedup qua `processed_emails`) → người duyệt → áp ETA.

**Deploy (production):** Internet → `caddy` (TLS Let's Encrypt tự động) → proxy
`webapp:1476`. `backend/Dockerfile` multi-stage (Node build `frontend/`→`dist/`,
Python copy vào, FastAPI mount StaticFiles + SPA fallback). Build context = repo
root.

## External Integrations

- **aisstream.io** (AIS WebSocket) — vị trí tàu realtime. **Critical** cho
  tracking; có `AIS_MODE=replay` + fixture để chạy offline deterministic.
- **Open-Meteo** (HTTP, không key) — wind/wave/current cho ETA Tầng 2. Critical
  cho điều chỉnh ETA; fallback êm khi lỗi.
- **StormGlass** (HTTP, có key, free tier) — tide/tidal window. Optional-ish;
  quota tính theo tổng số lô.
- **LLM endpoint OpenAI-compatible** (`base_url`/`api_key`/`model` qua env) —
  Agent A/B + Email Agent extract. Critical cho phần agent.
- **VesselFinder** (qua Playwright, deterministic scrape) — IMO/MMSI resolve.
- **Website hãng tàu** (qua Playwright MCP, agentic) — Carrier ETA baseline. Dễ
  vỡ (layout/CAPTCHA); fallback nhập tay.
- **IMAP mailbox delegate** — Email Agent đọc thư. Có allowlist an toàn.
- **OAuth Google/Microsoft** (Authlib) — đăng nhập, session JWT, audit trail.

Mọi lời gọi I/O ngoài phải nằm trong `integrations/` hoặc client riêng; domain
service CẤM import trực tiếp httpx/aiohttp/SDK (PROGRESS Option 1.5). Feature I/O
ngoài phải fallback êm, KHÔNG crash app.

## Constraints

- **Single-process:** ĐÚNG 1 uvicorn worker, KHÔNG `--workers >1`. Mọi background
  task (AIS, trail snapshot, weather/tide poll, Agent A scheduler, email poll)
  chạy embedded qua lifespan startup. State in-memory chỉ an toàn vì 1 process
  ghi (Spec §3.1).
- **Node KHÔNG chạm Postgres; Python KHÔNG chạm Redis** (IC§0.1). Container
  `playwright-mcp` không có `DATABASE_URL`.
- **Enum = `text` + `CHECK`** (không native enum); giá trị ASCII snake_case không
  dấu (`trung_binh`/`thap`, không `trung_bình`). `derive_monitoring_mode` là hàm
  duy nhất cài bảng Incoterm — mọi module dùng chung (IC§1.1).
- **Datetime tz-aware UTC** mọi nơi; cấm naive datetime (IC§15).
- **Config chỉ từ `.env`** (1 nguồn, không fallback chain); tên biến/default lấy
  từ IC§7. Cấm hardcode key/URL — qua `settings` (pydantic-settings). `.env.example`
  = template production; `.env.devtest2` = template dev/test sạch (commit được);
  `.env.devtest` = key thật user-owned, gitignored — **KHÔNG đọc/ghi đè, KHÔNG
  echo secret**.
- **Version pin bắt buộc** cho gói experimental (`@playwright/mcp`, `ag2`/`autogen`,
  `authlib`, `python-jose`, `mcp`) — chốt tại TASK-00, đọc docstring bản đã pin,
  không tự bump. Lock reproducibility: mọi task MODIFY requirements/package phải
  regenerate + commit lock (PROGRESS).
- **DB:** SQLAlchemy 2.x async (`asyncpg`) + Alembic; relationship `lazy="raise"`;
  query 2.0-style tường minh.
- **AIS subscribe = swap-and-replace:** gửi lại subscribe message phải chứa ĐỦ
  toàn bộ danh sách MMSI, không chỉ MMSI vừa đổi (Spec §3.1).
- **Interface boundary (Option 1.5):** CẤM tạo Interface/Protocol/Factory trừ khi
  có ≥2 implementation hoặc cần cho replay (AIS `AisSource` là ngoại lệ hợp lệ).
- **Verify:** logic lõi (eta_engine, normalize, derive_monitoring_mode, milestone
  map) = TDD; phần I/O = smoke/chạy thật. `pytest` (backend), `vitest` (frontend).
