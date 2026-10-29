# PROPOSAL / SPEC KỸ THUẬT — DEMO GIÁM SÁT LÔ HÀNG

> Tài liệu đặc tả kỹ thuật cho hệ thống giám sát lô hàng container (FCL nhập/xuất).
> Hình dạng interface chi tiết (env, API, DB) ở `Interface-Contract_v0.9.9.md`.
## 0. Cách đọc tài liệu này

Đây là bản thiết kế viết TRƯỚC khi code, mục đích ép chốt mọi quyết định kỹ thuật để lúc build không phải vừa làm vừa nghĩ. Đồng thời đây là nguồn tài liệu để viết mục 3.1, 3.2, 3.3.1 của bài luận sau này. Các chỗ còn cần xác minh với U&I trong quá trình thực tập được đánh dấu **[CẦN XÁC MINH]**. Các phần chưa cam kết cứng vào demo chính đánh dấu **[STRETCH GOAL]**.

---

## 1. Mục tiêu và phạm vi

### 1.1 Mục tiêu demo
Chứng minh tính khả thi của việc chuyển hoạt động CSKH sau bán từ *bị động* (khách hỏi mới tra) sang *chủ động* (hệ thống tự cập nhật hành trình + cảnh báo sớm khi ETA biến động).

### 1.2 Trong phạm vi (in-scope)
- Nhập lô hàng (nhập **hoặc** xuất, xem `shipment_direction` mục 4.1/5) bằng thông tin B/L + số container + **Incoterm** + tàu/voyage.
- **Onboarding tự động (mục 6.7, hai thành phần):** (a) **IMO Resolver** — script Playwright cứng (KHÔNG LLM) tra IMO/MMSI từ Vessel Name + Voyage trên VesselFinder; (b) **Carrier ETA Agent** — agentic qua Playwright MCP tra ETA baseline từ website hãng tàu (2-3 hãng demo). Có fallback nhập tay + cổng trạng thái `onboarding_status`.
- Theo dõi vị trí tàu thời gian thực qua AIS.
- Tính lại ETA động 2 tầng (rule-based) và cảnh báo khi lệch quá ngưỡng.
- Giao diện dạng "đơn hàng TMĐT" với thanh tiến trình theo cột mốc (milestone progress bar).
- ETA Reasoning Agent (AG2 — Agent A): điều phối tool + sinh nhận định chuyên gia định tính cạnh ETA baseline.
- Research Agent (AG2 — Agent B, Core): tìm + đánh giá tin bão/sự kiện ảnh hưởng tuyến, đưa nhận định tham khảo — có người xác minh (mục 6.3c).
- Agent email (Module 2): đọc hộp thư delegate, trích xuất thông báo rớt tàu/đổi lịch, đề xuất cập nhật ETA — có người duyệt.

### 1.3 Ngoài phạm vi (out-of-scope, ghi vào "hướng phát triển")
- Dự đoán ETA bằng Machine Learning (train model). Toàn hệ thống dùng rule-based + LLM diễn giải, KHÔNG train ML.
- Tích hợp EDI (IFTSTA/IFTSAI) thật với hãng tàu.
- Tích hợp hệ thống nội bộ U&I (TMS, CRM).
- **[v0.9.9]** Neo mực nước thủy triều theo **chart datum (LAT)** của hải đồ (offset datum theo từng cảng) — MVP dùng mực nước tương đối theo MSL từ API (xem §6.6, §9, §10). *(Dòng cũ "dùng bảng tĩnh tham chiếu" đã bỏ — từ v0.9.9 thủy triều lấy realtime qua StormGlass, xem §6.6.)*
- AIS vệ tinh (satellite-AIS) cho tuyến xuyên đại dương — MVP chỉ dùng AIS mặt đất (terrestrial), phủ gần bờ.

### 1.4 Tuyến demo
**[v0.9.8] Hai tuyến, một mỗi chiều** (khớp phạm vi mới §1.2/§5):
- **Nhập (E/F hoặc C/D):** một tuyến khu vực ngắn cập cảng Cát Lái, ví dụ Singapore / Hong Kong / Kaohsiung → Cát Lái (~3-5 ngày).
- **Xuất C/D (MỚI):** tuyến ngược — Cát Lái → một cảng khu vực ngắn (VD Singapore / Hong Kong / Kaohsiung, ~3-5 ngày) — để chứng minh nhánh xuất C/D hoạt động thật trong demo, không chỉ thiết kế trên giấy.

Lý do chọn tuyến ngắn cho cả hai chiều: AIS free phủ sóng tốt gần bờ, hành trình đủ ngắn để demo trọn vòng đời trong thời gian làm bài. Số lô theo dõi đồng thời: ~3-5 lô tổng cộng cả hai chiều (khớp free tier Stormglass — **[v0.9.9]** quota này nay dành cho **thủy triều**, xem mục 6.2/6.6 — quota tính theo tổng số lô, không phân biệt chiều).

---

## 2. Định vị hệ thống

Hệ thống là một **lớp hỗ trợ bổ sung (add-on layer)** — tổng hợp và hiển thị lại thông tin hành trình lô hàng cho bộ phận Kinh Doanh. Nó KHÔNG thay thế TMS, hệ thống hãng tàu, hay quy trình nghiệp vụ hiện có. Giá trị nằm ở chỗ: gom dữ liệu rải rác (vị trí tàu, thời tiết, dòng chảy, thông báo email) về một chỗ và biến nó thành cảnh báo chủ động.

---

## 3. Kiến trúc tổng thể

Trình bày theo 4 layer (dùng cho sơ đồ kiến trúc tổng quan ở mục 3.2 bài luận):

```
┌─────────────────────────────────────────────────────────────┐
│  LAYER 4 — FRONTEND (React + Leaflet)                         │
│  - Danh sách lô hàng (dạng đơn hàng)                          │
│  - Chi tiết lô: progress bar milestone + bản đồ tàu           │
│  - Ô "nhận định chuyên gia" + tín hiệu research "cần xác minh"│
│  - Hộp đề xuất chờ duyệt (email agent)                        │
└───────────────┬───────────────────────┬───────────────────────┘
                │ REST (CRUD lô hàng)    │ WebSocket (đẩy update realtime)
┌───────────────▼───────────────────────▼───────────────────────┐
│  LAYER 3 — AG2 MULTI-AGENT (LLM, OpenAI-compatible endpoint)   │
│  ┌─────────────────────────┐      ┌─────────────────────────┐ │
│  │ Agent A — ETA Reasoning │◄────►│ Agent B — Research Agent│ │
│  │ - Gọi tool Layer 2 (rule│      │ - Tool: web search       │ │
│  │   Tầng 1+2 → ETA chính) │      │ - Vòng: search → đánh    │ │
│  │ - Đánh giá kết quả B,   │      │   giá → (A yêu cầu search│ │
│  │   yêu cầu B search lại  │      │   lại theo hướng cụ thể) │ │
│  │   theo hướng cụ thể     │      │   → kết luận             │ │
│  │ - Tổng hợp "nhận định   │      │ - Trả Pydantic: event,   │ │
│  │   chuyên gia" cuối cùng │      │   relevance, route_impact│ │
│  │                         │      │   confidence, sources    │ │
│  └─────────────────────────┘      └─────────────────────────┘ │
│  A/B CHỈ chạy khi onboarding_status = resolved (mục 6.7)        │
│  KHÔNG tự quyết ETA baseline chính thức (xem mục 6.3b)          │
│                                                                  │
│  ┌────────────────────────────────────────────────────────┐   │
│  │ ONBOARDING (chạy 1 lần/lô, mục 6.7) — 2 phần tách:       │   │
│  │  (a) IMO Resolver  — deterministic, KHÔNG LLM            │   │
│  │      script Playwright cứng (trang VesselFinder cố định) │   │
│  │  (b) Carrier ETA Agent — agentic (LLM) qua Playwright MCP│   │
│  │      (mỗi hãng 1 layout → cần LLM suy luận)              │   │
│  │  (a) đi REST /scrape-jobs; (b) đi MCP transport riêng    │   │
│  │  → container playwright-mcp (KHÔNG chung 1 cửa). Python  │   │
│  │  KHÔNG chạm Redis. Python ghi vessel_registry + set      │   │
│  │  onboarding_status (mục 6.7 — Node KHÔNG chạm Postgres). │   │
│  └────────────────────────────────────────────────────────┘   │
│                                                                  │
│  Email Agent (Module 2) — TÁCH RIÊNG, không nằm trong hội thoại│
│  AG2 A↔B; kết nối qua DB (`agent_proposals`)                   │
└───────────────┬───────────────────────────────┬─────────────────┘
                │ gọi tool                        │ HTTP: POST /scrape-jobs
                │                                 │      GET /scrape-jobs/:id
                │                        ┌─────────▼──────────────────────┐
                │                        │ CONTAINER playwright-mcp (Node) │
                │                        │ - REST nhỏ (Express/Fastify)    │
                │                        │ - BullMQ Worker, concurrency 2-3│
                │                        │ - playwright-mcp quản lý các phiên Chromium trong cùng container; BullMQ giới hạn browser context đồng thời, mỗi job có context riêng│
                │                        │ - (a) script cứng VesselFinder  │
                │                        │ - (b) @playwright/mcp cho hãng  │
                │                        │        tàu (network transport)  │
                │                        └────────┬────────────────────────┘
                │                                 │ BullMQ (qua Redis)
                │                        ┌─────────▼──────────────┐
                │                        │ CONTAINER redis:alpine  │
                │                        │ (job queue, mục 6.7d)   │
                │                        └─────────────────────────┘
┌───────────────────────────▼─────────────────────────────────────┐
│  LAYER 2 — TOOL TÍNH TOÁN (FastAPI, chạy dưới dạng function)    │
│  ┌──────────────┐  ┌──────────────┐  ┌────────────────────┐    │
│  │ AIS Worker   │  │ Weather/Wave/│  │ ETA Engine         │    │
│  │ (nền, giữ    │  │ Current poll │  │ Tầng 1: động học   │    │
│  │  WS sống,    │  │ (Open-Meteo) │  │ Tầng 2: điều chỉnh │    │
│  │  realtime)   │  │ Tide poll    │  │ theo gió/dòng chảy │    │
│  │              │  │ (StormGlass) │  │                    │    │
│  └──────────────┘  └──────────────┘  └────────────────────┘    │
└───────────────────────────┬─────────────────────────────────────┘
                            │
                    ┌────────▼────────┐
                    │  LAYER 1 — DB    │
                    │  PostgreSQL      │
                    │  8 bảng nghiệp vụ + env_conditions + processed_emails = 10 bảng thực thi │
                    └──────────────────┘
```

**Lưu ý về bản chất Layer 2:** AIS Worker khác về bản chất so với Weather/Current poll — aisstream.io là WebSocket đẩy liên tục (server push), nên đây vẫn là một tiến trình nền chạy suốt (long-running), không phải "tool" được gọi theo yêu cầu như hai tool còn lại (REST pull). Gọi chung là "Layer 2" cho gọn sơ đồ, nhưng khi trình bày trong bài luận nên giữ phân biệt này để tránh hội đồng hỏi ngược "AIS sao gọi được như một function call". **[v0.9.9]** Nhãn nguồn trong sơ đồ đã cập nhật theo hoán đổi vai trò (mục 6.2/6.6): Open-Meteo lo wind/wave/**current** (1 lệnh gọi), StormGlass lo **tide**.

### 3.1 Vì sao AIS Worker phải tách riêng và giữ kết nối sống
aisstream.io là **WebSocket** — client mở một kết nối, gửi message subscribe (kèm bounding box vùng biển hoặc danh sách MMSI cần theo dõi), rồi server *đẩy* các bản tin vị trí về liên tục. Đây KHÔNG phải REST gọi GET một lần. Hệ quả thiết kế:

- Cần một tiến trình chạy nền **giữ kết nối mở suốt** (long-running), không phải request-response.
- Kết nối có thể rớt → cần logic **tự reconnect** + resubscribe.
- Mỗi bản tin nhận được → cập nhật vị trí tàu trong DB → kích hoạt ETA Engine tính lại → nếu vượt ngưỡng thì đẩy cảnh báo qua WebSocket lên frontend.
- Trong FastAPI, chạy worker này bằng một `asyncio` task khởi động cùng app (lifespan startup). **[v0.9.12 — CHỐT mô hình single-process]** Câu cũ để mở "*hoặc tách thành tiến trình riêng nếu muốn sạch hơn*" ⚠️ đã chốt cứng cho demo: **dùng ĐÚNG 1 uvicorn worker duy nhất, TẤT CẢ background worker (AIS worker, trail snapshot, weather/tide poll, Agent A scheduler, email poll) chạy embedded trong CÙNG process qua lifespan startup** — KHÔNG tách tiến trình, KHÔNG chạy `uvicorn --workers >1`. Lý do đúng tinh thần "right complexity / deliberately NOT Kafka" (§3.2): ở quy mô demo (3-5 lô, 1 async worker dư sức) một process là đủ, và **state in-memory** (mốc arrival first-seen của arrival detector, debounce recompute ETA) **an toàn vì chỉ có 1 process ghi**. Chạy nhiều worker/instance sẽ vỡ giả định này → xem giới hạn ở **§14 (Known Limitations)**. Dockerfile CMD `uvicorn app.main:app ...` KHÔNG có cờ `--workers` (mặc định 1) — kèm comment "# 1 worker: background tasks embedded, xem §3.1".

> **[v0.9.12] AIS_MODE — live vs replay:** AIS worker chọn nguồn theo biến `AIS_MODE` (IC§7): `live` (mặc định — nối aisstream.io WebSocket như mô tả ở đây) hoặc `replay` (đọc fixture JSON PositionReport, bơm vào **cùng đường xử lý upsert/broadcast/recompute**) để test/CI/E2E chạy deterministic không cần key/tàu thật. Live và replay dùng chung một `AisSource` Protocol; chi tiết cấu trúc module (`parser.py`/`stream_client.py`/`replay_source.py`) ở PROGRESS TASK-04.

> **Từ v0.9 (transit/rollover, mục 6.8):** danh sách MMSI worker subscribe đổi theo **chặng đang active** (`shipment_legs.is_active_leg=true`), và nhờ **pattern mirror** (mục 4.1/4.8) giá trị mới nhất luôn có sẵn ở `shipments.mmsi`. Theo tài liệu aisstream.io, subscription cập nhật được bằng cách **gửi lại subscribe message trên cùng kết nối đang mở** (không cần reconnect) — nhưng đây là thao tác **swap-and-replace, KHÔNG PHẢI merge**: message mới phải chứa **đủ toàn bộ** danh sách MMSI đang cần theo dõi (không chỉ MMSI vừa đổi), nếu không sẽ **mất subscribe của các lô khác** đang track. (Lưu ý: gửi đầy đủ danh sách là an toàn dù ngữ nghĩa server là replace hay merge, nên chọn cách này bất kể.)
>
> Vì vậy **code AIS worker CÓ đổi (nhẹ)**, không còn "y hệt cũ": thêm một **vòng kiểm tra định kỳ** (VD mỗi 60s) so danh sách MMSI hiện cần (`SELECT mmsi FROM shipments WHERE onboarding_status='resolved' AND status NOT IN ('arrived','delivered')` — loại lô đã tới nơi/giao xong khỏi danh sách subscribe) với danh sách đã subscribe gần nhất — nếu khác thì **gửi lại subscribe message đầy đủ**. Đây là lớp **an toàn nền** (self-healing), nhất quán với cách các nguồn khác trong spec cũng poll định kỳ (StormGlass 12h, weather 3-6h). Ngoài ra có **đường phản hồi nhanh**: khi `resolve_leg()`/`switch_active_leg()`/`resolve_and_activate_leg()` (mục 6.8) đổi tàu active, chúng bắn một `asyncio.Event` (hoặc đẩy vào queue nội bộ) để worker resubscribe **ngay**, không phải chờ tới chu kỳ poll kế tiếp. Pattern mirror vẫn là điểm mấu chốt: worker chỉ cần đọc `shipments.mmsi`, không phải JOIN `shipment_legs`.

### 3.1b Realtime vị trí vs. lịch sử trail — tách 2 tầng ghi để không phình DB
Ghi thẳng mọi bản tin AIS thô vào history sẽ phình bảng rất nhanh (aisstream có thể đẩy về mỗi vài giây/lần) mà phần lớn không có giá trị lưu trữ. Tách làm 2:

- **Vị trí hiện tại (`shipments.current_lat/current_lon/current_sog/current_cog/position_updated_at`)**: **UPDATE tại chỗ (upsert)**, không INSERT — mỗi lô chỉ có 1 dòng vị trí mới nhất. Cập nhật **realtime** theo đúng nhịp bản tin AIS nhận được. Đây là nguồn cho map hiển thị và cho ETA Engine tính lại/kích hoạt cảnh báo ngay lập tức — **không đợi theo chu kỳ 6h**, để giữ đúng giá trị "cảnh báo sớm, chủ động" là trọng tâm của module.
- **Trail lịch sử (bảng `vessel_trail`, xem mục 4.3)**: chỉ ghi thêm 1 điểm mới khi đã đủ **6 tiếng** kể từ điểm ghi gần nhất của lô đó. Giữ tối đa **12 điểm/lô** (~3 ngày, đúng độ dài tuyến demo 3-5 ngày) — điểm cũ hơn tự động bị đẩy ra khi có điểm mới (rolling window). Bảng này chỉ phục vụ vẽ vệt đường đi trên bản đồ, không phục vụ cảnh báo.

Nói cách khác: **cảnh báo thì realtime, lưu trữ thì lấy mẫu** — tách được giá trị nghiệp vụ (phát hiện sớm) ra khỏi chi phí vận hành (storage), và đây là một quyết định kỹ thuật đáng đưa vào bài luận như bằng chứng cân nhắc giữa hiệu năng và tính khả thi.

### 3.2 Vì sao KHÔNG dùng Kafka + Flink
Tải thực tế: vài chục đến vài trăm lô hàng, mỗi tàu phát AIS vài phút/lần. Một async worker xử lý dư sức. Kafka + Flink sinh ra cho hàng chục nghìn event/giây, nhiều consumer, stateful windowing phức tạp — dùng ở đây là over-engineering và sẽ là điểm yếu khi bảo vệ ("tại sao cần Kafka cho 50 lô?"). Ghi Kafka/Flink vào mục "hướng mở rộng khi scale lên hàng nghìn lô realtime" là cách trình bày đúng: thể hiện biết công nghệ + biết khi nào nên dùng.

### 3.3 Stack chốt
- **Frontend:** React + Leaflet (bản đồ tàu). Progress bar milestone tự dựng (không cần thư viện nặng).
- **Backend:** Python + FastAPI (REST + WebSocket + async AIS worker). Chọn Python vì phần agent (LLM/xử lý email/tool-calling) dựa nhiều vào hệ sinh thái Python.
- **DB:** PostgreSQL.
- **Agent framework:** AG2 (AutoGen) cho Layer 3 — điều phối 2 agent (ETA Reasoning + Research), lo sẵn vòng lặp tool-calling + retry + quản lý lượt hội thoại (mục 3.5).
- **Structured output:** Pydantic model cho kết quả Research Agent (`event, relevance, route_impact, confidence, sources`) — validate + retry khi sai format.
- **Cache:** một bảng nhỏ trong Postgres hoặc Redis — dùng cho cache kết quả research theo tuyến (mục 6.3d). MVP có thể dùng bảng Postgres cho gọn, chưa cần Redis.

### 3.4 Cấu hình LLM (OpenAI-compatible)
- Gọi LLM qua endpoint tương thích OpenAI: cấu hình `base_url`, `api_key` (sk-...), `model` qua **biến môi trường** (`.env`), KHÔNG hardcode trong code.
- Cho phép đổi nhà cung cấp/model mà không sửa logic — chỉ đổi env.
- Dùng cơ chế **tool calling / function calling** chuẩn OpenAI để các agent gọi các tool ở Layer 2 và tool research.
- **KHÔNG train, KHÔNG fine-tune model** — chỉ gọi API sẵn có. Điều này củng cố lập luận "không dùng ML" của bài luận: mọi con số ETA đều do công thức rule-based sinh ra, LLM chỉ điều phối + diễn giải.

### 3.5 Vì sao DÙNG AG2 (AutoGen) cho Layer 3

Đây là quyết định kiến trúc quan trọng, nên trình bày rõ cả *lý do dùng* lẫn *cách phòng thủ* khi bảo vệ.

**Lý do dùng — AG2 lo sẵn phần boilerplate đáng kể:** nếu tự viết vòng lặp tool-calling từ đầu thì phải tự lo: quản lý lượt hội thoại giữa 2 agent, **retry khi tool fail**, **xử lý lỗi** (timeout, exception từ tool, LLM trả sai format), và điều phối khi agent này cần kết quả của agent kia. AG2 gói sẵn các phần này. Với cấu hình **2 agent thật sự** (ETA Reasoning + Research), đây là công việc điều phối thật, không phải 1 agent lẻ — nên framework có chỗ dùng chính đáng.

**Cấu hình 2 agent (mục 6.3b, 6.3c):**
- **Agent A — ETA Reasoning:** điều phối chính, gọi tool Layer 2 (ETA rule-based Tầng 1+2), tổng hợp nhận định chuyên gia. Khi cần tín hiệu khó rule-hóa (bão, sự kiện tuyến) thì hỏi Agent B.
- **Agent B — Research Agent:** dùng tool web search, chạy vòng search → đánh giá → kết luận, trả kết quả dạng Pydantic.
- **Có vòng phản hồi thật giữa A↔B:** A không chỉ nhận kết quả B một chiều — A **đánh giá** kết quả B, nếu chưa đủ (VD "cơn bão đó xa tuyến") thì **yêu cầu B search lại theo hướng cụ thể** (VD "chỉ tập trung eo Malacca trong 48h tới"). Chính vòng phản hồi này biện minh cho "multi-agent" — không phải 1 agent gọi 1 tool.

**Cách phòng thủ khi bảo vệ (quan trọng — trình bày THÀNH THẬT, không oversell):**
- Nếu hội đồng hỏi "sao cần framework multi-agent?", trả lời thẳng: *"Em dùng AG2 để nó lo vòng lặp tool-calling, retry khi tool lỗi, và điều phối 2 agent — nhờ đó em tập trung vào logic nghiệp vụ thay vì viết lại hạ tầng."* Đây là lý do hợp lệ, đúng bản chất.
- KHÔNG khoa trương thành "hệ multi-agent phức tạp". Sự khiêm tốn ("dùng đúng công cụ cho việc điều phối 2 agent") mạnh hơn là thổi phồng.
- Đối chiếu có ý thức với quyết định "không Kafka": Kafka bị loại vì tải thực tế không cần (vài chục lô, 1 async worker là đủ). AG2 thì *có* việc để làm (điều phối 2 agent + retry/error handling), nên khác bản chất — biết dùng công cụ đúng chỗ, và cũng biết chỗ nào không cần (Kafka).

**Rủi ro đã biết của AG2** (nêu ở mục 9 để trung thực học thuật): là dependency tương đối nặng, API còn thay đổi giữa version. Chốt version cụ thể trong `requirements.txt` để demo tái lập được.

**Structured output vẫn dùng Pydantic:** kết quả Research Agent định nghĩa bằng Pydantic model (`event, relevance, route_impact, confidence, sources`), validate + retry khi sai format — độc lập với việc dùng AG2.

### 3.6 Điều khiển browser: deterministic cho trang cố định, Playwright MCP cho trang đa dạng

**Vấn đề gốc (từ v0.6):** để tracking AIS phải subscribe theo **MMSI/IMO**, nhưng chứng từ đầu vào (B/L, Booking Confirmation) chỉ cho **Vessel Name + Voyage**. Cần một lớp tự động (a) tra IMO/MMSI từ tên tàu (VesselFinder), và (b) tra ETA baseline từ website hãng tàu.

**Nguyên tắc chốt ở v0.7 — chỉ nhường quyền quyết định cho LLM ở chỗ THẬT SỰ cần suy luận:**

| Việc | Đặc điểm trang | Cách làm | Lý do |
|---|---|---|---|
| **(a) IMO Resolver** (VesselFinder) | **1 trang cố định**, luồng thao tác y hệt mỗi lần (search tên → đọc bảng → lọc voyage) | **Script Playwright viết cứng (deterministic), KHÔNG qua LLM/MCP** | Cho LLM tự "click" từng bước trên trang cấu trúc cố định vừa tốn thêm vòng gọi model (chậm, tốn token) vừa **kém tin cậy hơn code cứng**. Không có suy luận thật để nhường |
| **(b) Carrier ETA** (web hãng tàu) | **Mỗi hãng 1 layout khác nhau**, ETA nằm chỗ khác nhau | **Agentic qua Playwright MCP (LLM tự quyết)** | Đây đúng là chỗ cần LLM suy luận "trang này ETA ở đâu, click vào đâu" — nhường quyền cho LLM là chính đáng |

Đây là một dạng **"đúng độ phức tạp cho đúng việc"** — cùng tinh thần với quyết định "không Kafka" và "dùng AG2 đúng chỗ có điều phối thật". Nhường LLM ở nơi cần suy luận (nhiều layout), giữ code cứng ở nơi có logic cố định.

**Playwright MCP (Microsoft `@playwright/mcp`) — cho phần (b):**
- MCP (Model Context Protocol) expose sẵn các **tool trình duyệt** (mở trang, click, điền, đọc DOM/snapshot) để agent LLM gọi qua function-calling — **không phải tự viết code điều khiển Playwright** cho từng bước.
- Chạy như **một tiến trình Node riêng** (container riêng, mục 3.7). Vì tách container, MCP server phải chạy ở **network transport (HTTP/SSE hoặc Streamable HTTP tùy version đã pin)**, KHÔNG dùng stdio — stdio chỉ dùng được khi client và server chung một process. Backend gọi vào qua network trong cùng compose network. **[Chốt endpoint/flag đúng theo version `@playwright/mcp` đã pin — spec để version-agnostic, không hardcode đường dẫn.]**

**Đã cân nhắc và LOẠI — LangChain `PlaywrightBrowserToolkit`:** sẽ kéo nguyên framework LangChain vào chỉ để lấy bộ tool browser, trong khi Layer 3 đã dùng AG2. Hai framework agent song song là điểm yếu khi bảo vệ ("tại sao vừa AG2 vừa LangChain?") và làm nặng dependency. Playwright MCP trung lập với framework agent (giao tiếp qua giao thức MCP), gắn vào AG2 gọn hơn.

**Cân nhắc trung thực (nêu ở mục 9):** cách agentic (LLM tự đọc trang + quyết thao tác) cho phần (b) **linh hoạt** hơn scraper cứng theo từng hãng, nhưng **tốn token** hơn và **dễ vỡ** khi web đổi layout, chặn bot, hoặc bật CAPTCHA. Đây là đánh đổi có chủ đích (ưu tiên linh hoạt + không tự code browser cho từng hãng). Giảm thiểu bằng: cache `vessel_registry`, chạy một lần (không định kỳ), fallback về nhập tay (mục 6.7).

### 3.7 Kiến trúc triển khai (docker-compose, web app thật)

Demo được đóng gói thành **web app thật có deploy** (không chỉ chạy localhost) — vừa là minh chứng cho bài luận, vừa là project portfolio đưa lên GitHub làm reference. Dùng **docker-compose** để lên VPS chỉ cần `docker compose up`:

```
   Internet (HTTPS) ─────┐
                         ▼
┌────────────────────────────────────────────────────────────────┐
│  VPS (docker-compose)                                            │
│  ┌────────────────────────┐                                     │
│  │ container: caddy         │  reverse proxy + TLS tự động        │
│  │ - Let's Encrypt auto     │  (xin/gia hạn cert, không cronjob)  │
│  └───────────┬────────────┘                                     │
│              │ proxy nội bộ (HTTP)                                │
│  ┌───────────▼────────────┐                                     │
│  │ container: webapp        │                                    │
│  │ - FastAPI (REST + WS)    │   IMO Resolver: HTTP POST          │
│  │ - Auth OIDC (Authlib)    │──────/scrape-jobs────────┐        │
│  │ - AIS worker (async)     │   Carrier ETA: MCP (SSE)  │        │
│  │ - AG2 agents A/B         │────────────────────┐     │        │
│  │ - Onboarding điều phối    │                     │     │        │
│  │ - Frontend (build tĩnh)  │                     │     │        │
│  └───────────┬────────────┘                      │     │        │
│              │                          ┌─────────▼─────▼──────┐ │
│      ┌───────▼────────┐                 │ container:playwright- │ │
│      │ container: db    │                │ mcp (Node)            │ │
│      │ PostgreSQL       │   (Python ghi;  │ - @playwright/mcp(SSE)│ │
│      └──────────────────┘                │ - REST /scrape-jobs   │ │
│              ▲                            │   (Express/Fastify)   │ │
│              │                            │ - BullMQ Worker        │ │
│      ┌───────┴────────┐                   │   concurrency=2-3      │ │
│      │ container: redis │◄──BullMQ queue──┤ - playwright-mcp quản lý các phiên Chromium trong cùng container; BullMQ giới hạn browser context đồng thời, mỗi job có context riêng  │ │
│      │ redis:alpine     │                 │   = 1 browser context  │ │
│      └──────────────────┘                 └───────────────────────┘ │
└────────────────────────────────────────────────────────────────┘
   ↑ LLM qua endpoint OpenAI-compatible (mục 3.4) — bên ngoài
   ↑ Google/Microsoft OIDC (đổi code lấy id_token) — bên ngoài
```

**container `playwright-mcp` (Node) — có HAI cửa vào (REST `/scrape-jobs` cho IMO Resolver; MCP transport riêng cho Carrier ETA), Chromium do chính container này quản lý, BullMQ giới hạn số browser context đồng thời:**
- **Cửa (1) — REST `/scrape-jobs` + BullMQ Worker (cho IMO Resolver deterministic, mục 6.7a):** backend Python (lớp onboarding) gọi `POST /scrape-jobs` → Node enqueue job vào BullMQ (lưu trên Redis) → Worker (concurrency 2-3) chạy script Playwright cứng → trả kết quả JSON qua `GET /scrape-jobs/:id` (poll); **Python** poll về rồi tự validate + ghi `vessel_registry`/`shipments` (Node KHÔNG chạm Postgres — IC§0.1). **Python KHÔNG bao giờ chạm Redis** — ranh giới ngôn ngữ Python↔Node giải quyết bằng **HTTP** (giao thức chuẩn, ổn định), không chia sẻ format Redis nội bộ.
- **Cửa (2) — MCP network transport (cho Carrier ETA agentic, mục 6.7b):** Carrier ETA Agent (AG2, Python) gọi tool trình duyệt qua MCP để LLM tự đọc trang hãng tàu. Transport là **HTTP/SSE hoặc Streamable HTTP** (không stdio — vì khác container, mục 3.6).

**Vì sao cần Worker Pool + Job Queue (BullMQ + Redis) cho IMO Resolver:** ở quy mô lớn (bulk import), nhiều request onboarding tới gần như cùng lúc, mỗi phiên scrape cần launch/giữ một browser context (nặng RAM) — **không thể xử lý song song không giới hạn**, dễ OOM. Cần: (1) **cap số browser context đồng thời** (concurrency 2-3, config 1 dòng), (2) **hàng đợi** cho job vượt trần, (3) **retry/timeout có sẵn** không tự viết lại logic queue. BullMQ (Node) lo cả ba.
- **Phân biệt có ý thức với "không Kafka" (mục 3.2):** Kafka giải bài toán **throughput** (hàng chục nghìn event/giây) — không tồn tại ở đây. Job queue ở đây giải bài toán **tài nguyên đắt không chạy song song vô hạn được** (browser context) — có thật khi bulk import. **Khác bản chất**, nên không mâu thuẫn với lập luận loại Kafka.
- **Chi phí:** thêm container `redis:alpine` — miễn phí, chỉ tốn ~30-50MB RAM lúc idle, không đáng kể với VPS demo.
- **MVP bắt buộc Redis + BullMQ và Chromium do container `playwright-mcp` quản lý; mỗi job có browser context riêng.** `asyncio.Semaphore(2-3)` chỉ là phương án ngoài MVP/scale-ahead, không được dùng thay thế trong demo.

**container `webapp` (Python):** FastAPI (REST + WebSocket + AIS worker) + AG2 (Agent A/B + Carrier ETA Agent) + client gọi IMO Resolver qua HTTP `/scrape-jobs` + **Auth OIDC (Authlib, mục 3.8)** + frontend build tĩnh phục vụ qua chính FastAPI.

**container `caddy` (reverse proxy + TLS):** cổng vào công khai duy nhất — nhận HTTPS từ internet, tự xin/gia hạn cert Let's Encrypt (**không cần cronjob certbot**, khác nginx), proxy nội bộ (HTTP) tới `webapp`. Chỉ container này expose port ra ngoài; `webapp`/`db`/`redis`/`playwright-mcp` chỉ nói chuyện trong compose network. Ở môi trường test cục bộ (port **1476**) chưa cần caddy — chỉ bật khi deploy domain thật.

**container `db`:** PostgreSQL (có thể tách hoặc dùng managed DB tùy VPS).

**Lưu ý build đa kiến trúc (tránh bẫy build local → deploy VPS):**
- Compose xử lý được việc build trên máy dev (Windows/Mac) rồi chạy trên VPS (Linux) — container đóng gói sẵn môi trường Linux, OS host không quan trọng.
- **Nhưng** nếu build trên máy ARM (Apple Silicon) → image `arm64` → lên VPS `amd64` sẽ chạy qua emulation (rất chậm) hoặc lỗi. Cách tránh: build đúng kiến trúc đích bằng `docker buildx build --platform linux/amd64 ...`.
- Cho container `playwright-mcp`: dùng **image chính thức Microsoft `mcr.microsoft.com/playwright`** — đã multi-arch + cài sẵn system libs cho Chromium (`libnss3`, `libatk`, font...), tránh luôn loại lỗi "thiếu thư viện hệ thống" rất hay gặp khi cài Playwright thủ công.

**[Bảo mật khi deploy web app thật]** vì là web app có địa chỉ công khai: **xác thực người dùng** đã được thiết kế cụ thể ở **mục 3.8** (OAuth/OIDC), còn LLM key/aisstream key qua **biến môi trường** (mục 3.4), không commit vào repo.

**Structured output vẫn dùng Pydantic (nhắc lại — không đổi):** áp dụng cho cả kết quả IMO Resolver phân giải tàu (mục 6.7a) — model `{vessel_name, imo, mmsi, matched_voyage, confidence, source_url}` — dù (a) là script cứng, đầu ra vẫn validate qua Pydantic trước khi ghi DB.

### 3.8 Xác thực người dùng (OAuth/OIDC — vá lỗ hổng audit trail)

**Vì sao cần (không chỉ là "đăng nhập"):** hệ thống có nhiều thao tác do NGƯỜI thực hiện — duyệt/từ chối `agent_proposals`, xác minh `research_findings`, bấm retry / nhập tay IMO ở onboarding. Nếu không định danh *ai* làm thì mâu thuẫn với chính mục tiêu **"mọi thao tác truy vết được"** (checklist 11b). Vậy auth ở đây phục vụ **audit trail** trước, chặn truy cập sau. Bảng `users` (mục 4.7) + cột `decided_by`/`verified_by` là phần "ai làm"; phần này là "làm sao biết đúng người".

**Không tự quản mật khẩu — đăng nhập qua provider (OIDC):**
- Thư viện **Authlib** (Python) hỗ trợ sẵn cả Google lẫn Microsoft qua chuẩn **OpenID Connect** — không viết riêng cho từng provider.
- **KHÔNG có cột `password`** — hoàn toàn dựa vào provider xác thực (bớt trách nhiệm lưu/băm mật khẩu, một mặt tấn công ít đi).
- **Phân biệt rõ với Email Agent (mục 7):** đăng nhập chỉ xin `email + profile`, **KHÔNG xin quyền đọc Gmail/Outlook**. Đọc mailbox là việc riêng của Module 2 (delegate mailbox), đừng nhầm hai luồng OAuth này.

**Flow (Authorization Code + PKCE + state — chuẩn cho web app có frontend riêng):**
```
1. User bấm "Đăng nhập bằng Google" (hoặc Microsoft) trên frontend
   → backend sinh `state` (chống CSRF) + PKCE `code_verifier`/`code_challenge`,
     lưu tạm vào COOKIE HANDSHAKE (Starlette SessionMiddleware — cookie riêng,
     KHÁC cookie JWT phiên ở bước 6), rồi redirect sang trang login của provider.
2. User đăng nhập bên provider → đồng ý cấp quyền (chỉ email + profile).
3. Provider redirect về backend (kèm `state` gốc):
   GET /auth/callback/google?code=...&state=...   |   .../microsoft?code=...&state=...
4. Backend ĐỐI CHIẾU `state` trả về với `state` đã lưu (khác → từ chối, chống CSRF),
   rồi dùng `code` + `code_verifier` đổi lấy access_token + id_token (Authlib lo bước này)
   → giải mã id_token: email, name, provider_sub.
5. Kiểm tra bảng users theo provider_sub:
   - đã có → login, cập nhật last_login_at.
   - chưa có → tạo user mới (role mặc định = user). [Đăng ký MỞ cho mọi tài khoản — xem mục 9]
6. Backend TỰ phát hành session JWT riêng của hệ thống (ký bằng secret nội bộ),
   set cookie với các flag HttpOnly + Secure + SameSite=Lax (xem dưới)
   → frontend dùng cookie này gọi REST API. KHÔNG dùng thẳng token provider.
```

**Vì sao bước 6 tự phát hành JWT riêng (không dùng thẳng token Google/Microsoft):** access token của provider có hạn ngắn + phạm vi gắn với provider, không nên mang xuyên suốt app. Sau khi xác thực xong, hệ thống phát hành session riêng (JWT ký bằng secret) tách biệt hoàn toàn với provider — đây là **pattern chuẩn**, không phải phức tạp thừa.

**`state` parameter — chống CSRF trong chính OAuth flow (bước 1/3/4):** `state` là chuỗi ngẫu nhiên backend sinh ở bước 1, gửi kèm sang provider, rồi đối chiếu khi provider redirect về (bước 4). Nó bảo đảm request callback thật sự bắt nguồn từ **chính phiên user vừa bấm đăng nhập**, không phải kẻ tấn công chèn `code` của người khác vào phiên nạn nhân (login CSRF / code injection). Lưu ý `state` **bù cho** PKCE chứ không thay: PKCE chống *chặn/đánh cắp* `code` (code interception), `state` chống *inject* `code` sai phiên. **Authlib xử lý `state` tự động** khi dùng đúng API (`authorize_redirect` sinh + lưu, `authorize_access_token` verify) — spec ghi rõ ra đây để không hiểu ngầm, và để khi bảo vệ trả lời được câu "chống CSRF ở đâu".

**Thuộc tính cookie — HAI cookie TÁCH BIỆT, lý do `SameSite` khác nhau (bắt buộc quy định, không để trần):** hệ thống có hai cookie khác nhau về mặt kỹ thuật, không được gộp lý do:

**(A) Cookie handshake (Starlette `SessionMiddleware`, lưu `state` + `code_verifier`):** sống ngắn, chỉ tồn tại giữa bước 1 (redirect đi) và bước 4 (callback về).
- **`SameSite=Lax` là BẮT BUỘC** ở cookie này. Callback (bước 3) là một **top-level GET navigation từ `google.com`/`microsoft` quay về `/auth/callback`** — cookie handshake phải được trình duyệt gửi kèm ở đúng request đó để backend đọc lại `state`/`code_verifier`. Nếu để **`Strict`, trình duyệt KHÔNG gửi cookie** (request tới từ origin provider) → backend đọc `state` rỗng → **gãy flow**. `Lax` cho phép cookie trên top-level GET → đúng cái cần. Đây là cookie mà lý do "Strict gãy flow" áp dụng CHÍNH XÁC.
- `HttpOnly` + `Secure` như dưới. Cookie này Authlib/SessionMiddleware set, không phải app tự set.

**(B) Cookie JWT phiên đăng nhập (bước 6, app tự set):** sống dài, mang session sau khi đăng nhập xong.
- **`Strict` không gãy ở bước SET cookie và các API call sau đó, nhưng KHÔNG gãy là có điều kiện — phụ thuộc redirect ngay sau callback đáp vào đâu:** lúc callback xử lý thì cookie JWT *chưa tồn tại* (nó được set trong chính response của `/auth/callback`; `SameSite` chỉ chi phối việc GỬI cookie ở request tương lai, không chi phối lúc SET), và các fetch/XHR từ SPA cùng origin sau đó vẫn gửi cookie `Strict` bình thường. Nhưng `/auth/callback` set cookie xong thường trả **302 redirect** về `/` hoặc route đích — request redirect này **vẫn thuộc chuỗi navigation cross-site khởi nguồn từ provider** (google.com/microsoft), và theo hành vi trình duyệt, cookie `Strict` **chưa được gửi kèm** trên request đó, kể cả khi chặng redirect là same-site (đây là gotcha có thật, hay gây "login loop" với OAuth). Hệ quả: nếu redirect sau login đáp vào một route được middleware bảo vệ → server không thấy cookie ở lần đầu → đá về login → với `Strict`, flow **gãy thật ngay lần đầu**. Nếu đáp vào SPA shell công khai rồi JS mới gọi API (các fetch sau đều same-site thật sự) → không gãy.
- **Vẫn chọn `SameSite=Lax` cho cookie JWT** — không phải (chỉ) vì "Strict gãy login flow ngay bước set cookie", mà vì hai lý do cộng lại: **(1)** request redirect ngay sau callback vẫn thuộc chuỗi navigation cross-site nên `Strict` có thể gãy flow lần đầu nếu redirect đáp vào route bảo vệ (xem trên); **(2)** **trải nghiệm điều hướng từ ngoài vào** — với `Strict`, nếu user mở app bằng top-level navigation từ bên ngoài (click link trong email, mở bookmark tới một route được bảo vệ), cookie không được gửi ở request đầu → server tưởng chưa đăng nhập → đá về login dù phiên còn hợp lệ. `Lax` cho gửi cookie trên top-level GET nên vào mượt ở cả hai trường hợp.
- **KHÔNG dùng `None`** ở cả hai: frontend tĩnh do chính `webapp` phục vụ nên **cùng origin** với backend sau caddy → không có nhu cầu cookie cross-site.

**Ba flag áp cho CẢ hai cookie:**
- **`HttpOnly`** — JavaScript không đọc được cookie → giảm rủi ro đánh cắp qua XSS.
- **`Secure`** — chỉ gửi qua HTTPS (khớp caddy auto-TLS ở production, mục 3.7). *Test cục bộ qua `http://localhost:1476`: Chrome/Firefox coi `localhost` là secure context nên cookie `Secure` vẫn hoạt động, **trừ Safari** (không áp dụng ngoại lệ này cho `http://localhost`); để chắc, bật/tắt `Secure` theo biến môi trường (bật ở production HTTPS, có thể tắt ở local http) — tránh "mất cookie khó hiểu" khi test.*
- **`SameSite`** — như phân tích (A)/(B) ở trên (cả hai đặt `Lax`, nhưng vì lý do khác nhau).

**Định danh bất biến:** khóa tra `users` là `provider_sub` (subject ID từ provider), **không phải email** — email hiển thị có thể đổi, `provider_sub` thì không → tránh trùng/mất dấu người dùng khi họ đổi tên/email.

**Thành phần cần làm:**
- **Backend:** tích hợp Authlib; endpoint `/auth/login/{provider}` + `/auth/callback/{provider}`; middleware verify session JWT cho các route cần bảo vệ.
- **DB:** bảng `users` (mục 4.7).
- **Frontend:** 2 nút "Đăng nhập bằng Google / Microsoft", lưu session cookie, redirect logic.

**Redirect URI:**
- **Test cục bộ (hardcode port `1476`):** `http://localhost:1476/auth/callback/google` và `http://localhost:1476/auth/callback/microsoft` — đăng ký sẵn ở Google Cloud Console + Azure Portal.
- **Production:** đăng ký **thêm** redirect URI theo domain thật (qua HTTPS/caddy, mục 3.7) — không bỏ URI test, chỉ bổ sung.

> Việc tự đăng ký app OAuth ở Google Cloud Console + Azure Portal (client_id/secret) là thao tác thủ công một lần, làm ngoài code; secret nạp qua biến môi trường (mục 3.4), không commit.

---

## 4. Mô hình dữ liệu (PostgreSQL)

### 4.1 Bảng `shipments` — lô hàng + vị trí hiện tại

Bảng trung tâm. **Vị trí hiện tại nằm ngay trong bảng này** (upsert tại chỗ), KHÔNG tách bảng riêng — mỗi lô chỉ có 1 dòng vị trí mới nhất.

| Cột | Kiểu | Ghi chú |
|---|---|---|
| `id` | serial PK | |
| `bl_number` | text | Số B/L, nhập tay |
| `container_no` | text | Số container |
| `incoterm` | text/enum | **Trường định tuyến** (mục 5) — kết hợp với `shipment_direction` để quyết định Email Agent có áp dụng không, và áp dụng theo mode nào |
| `shipment_direction` | text/enum | **[v0.9.8]** `import` \| `export`. Nhập cùng lúc với `incoterm` khi tạo lô — cặp `(shipment_direction, incoterm)` quyết định `monitoring_mode` (mục 5). UI **ẩn nhóm Incoterm E/F** khỏi dropdown khi `export` được chọn (tổ hợp xuất E/F ngoài phạm vi, không hỗ trợ) |
| `carrier` | text | Hãng tàu |
| `vessel_name` | text | Tên tàu |
| `imo` | text null | IMO number (định danh tàu, không đổi theo đời). **Có thể null lúc tạo lô** — điền sau khi IMO Resolver phân giải (mục 6.7a). **v0.9: mirror của leg active** |
| `imo_resolved_via` | text/enum null | **Nguồn IMO cho lô này (mục 6.7a):** `cache_hit` \| `deterministic_scrape` \| `manual` — khác `vessel_registry.resolved_via` (nguồn gốc của IMO trong cache); trường này ghi cách lô cụ thể lấy được IMO. **v0.9: mirror của leg active** |
| `mmsi` | text null | MMSI — khóa để subscribe AIS (aisstream.io). **Null cho tới khi `onboarding_status = resolved`**. **v0.9: mirror của leg active** |
| `voyage_no` | text | Số chuyến. Dùng để phân định khi trùng tên tàu (mục 6.7a) |
| `pol` | text | Port of Loading. **[v0.9.8]** Nhập: cảng nước ngoài. Xuất: cảng VN (demo: Cát Lái) |
| `pod` | text | Port of Discharge. **[v0.9.8]** Nhập: cảng VN (demo: Cát Lái). Xuất: cảng nước ngoài |
| `eta_original` | timestamptz null | ETA gốc. Từ Carrier ETA lookup (mục 6.7b) hoặc Booking Confirmation/B/L **nhập tay** (fallback) |
| `eta_original_source` | text/enum null | **Nguồn của `eta_original` (mục 6.7b):** `carrier_scrape` \| `manual` — để trace baseline đến từ scrape hay nhập tay |
| `eta_current` | timestamptz | ETA mới nhất sau khi tính lại (kết quả Tầng 2) |
| `atd` | timestamptz null | Actual Time of Departure (mốc tính deviation) — **null trước khi tàu khởi hành** (milestone `[Tàu khởi hành ATD]` chưa qua); ETA Engine guard theo cột này trước khi tính `deviation_pct` (§6.3, v0.9.6) |
| `status` | text/enum | `new` / `on_sea` / `arrived` / `delivered` (cơ sở suy diễn milestone, mục 6.1) |
| `shipment_type` | text/enum | **`direct` \| `transit`, mặc định `direct`** (v0.9, mục 6.8). Do Carrier ETA Agent set khi phát hiện có cảng chuyển tải trung gian (>2 điểm POL→POD). `direct` = 1 chặng; `transit` = nhiều chặng trong `shipment_legs` |
| `onboarding_status` | text/enum | **Cổng trạng thái phân giải tàu (mục 6.7):** `pending` → `resolved` \| `manual_required`. AIS worker chỉ subscribe khi `resolved`; Agent A/B chỉ chạy khi `resolved`. **⚠️ Từ v0.9 (mục 6.8): đây là BẢN MIRROR của leg đang active (`shipment_legs.is_active_leg=true`), KHÔNG set độc lập — luôn ghi qua `resolve_leg()`** |
| `onboarding_error` | text null | **Lý do fail cụ thể (mục 6.7):** VD `captcha`, `not_found`, `ambiguous_name`, `timeout`, `login_required` — để hiển thị cho người dùng + trace, thay vì chỉ biết "manual_required". **v0.9: mirror của leg active** |
| `monitoring_mode` | text/enum | `auto_email` \| `manual` — **[v0.9.8]** suy ra từ cặp `(shipment_direction, incoterm)`, không còn 1 chiều theo `incoterm` đơn — xem bảng đầy đủ ở mục 5 |
| `current_lat` | double precision | Vị trí hiện tại — **upsert realtime** từ AIS |
| `current_lon` | double precision | |
| `current_sog` | double precision | Speed Over Ground (knots) |
| `current_cog` | double precision | Course Over Ground (độ) |
| `position_updated_at` | timestamptz | Thời điểm bản tin AIS gần nhất |
| `delivered_at` | timestamptz null | **Mốc neo dọn dữ liệu** (mục 4.9) |
| `created_at` / `updated_at` | timestamptz | |

> **⚠️ Pattern mirror (v0.9 — quan trọng, mục 6.8):** Từ khi có `shipment_legs` (mục 4.8), các cột `onboarding_status`, `imo`, `mmsi`, `imo_resolved_via`, `onboarding_error` trên `shipments` là **BẢN SAO (mirror) của leg đang active** (`shipment_legs.is_active_leg = true`), KHÔNG được set độc lập. **Nguồn sự thật là `shipment_legs`**; `shipments` chỉ là bản mirror tiện tra để AIS worker + Agent A/B **đọc thẳng không phải JOIN** và **không phải đổi code** (chúng vẫn query `shipments.mmsi`/`onboarding_status` như từ v0.6). Quy tắc "1 nguồn ghi, 2 nơi đọc": mọi lần ghi đi qua **`resolve_leg()`** (mục 6.7a) trong **1 transaction** — cập nhật `shipment_legs` trước, nếu leg đó đang active thì mirror lên `shipments`. Với lô `direct` (1 leg) hai bên luôn khớp; với `transit` chúng khác nhau hợp lệ (VD leg 2 còn `pending` trong khi leg 1 active đã `resolved`). Đây là chỗ dễ tạo lỗi "duplicate authority" nếu ghi trực tiếp `shipments` bỏ qua leg — nên checklist 11b có 1 dòng chốt điều này.

### 4.2 Bảng `eta_history` — lịch sử ETA (audit trail)

Mỗi lần ETA được tính lại/thay đổi thì ghi thêm 1 dòng. Bằng chứng "hệ thống chủ động phát hiện biến động" — cho phép vẽ đường "ETA thay đổi theo thời gian", quan trọng cho bài luận (mục 3.3.2/3.3.3).

| Cột | Kiểu | Ghi chú |
|---|---|---|
| `id` | serial PK | |
| `shipment_id` | int FK | |
| `eta_value` | timestamptz | Giá trị ETA tại thời điểm ghi (kết quả Tầng 2) |
| `source` | text/enum | `original` \| `ais_recompute` \| `weather_adjusted` \| `email_agent` \| `manual` |
| `deviation_pct` | double precision | % lệch so với `eta_original` |
| `note` | text null | Nhận định định tính của Agent A (nếu có) đính kèm |
| `recorded_at` | timestamptz | |

### 4.3 Bảng `vessel_trail` — vệt đường đi (lấy mẫu)

Chỉ phục vụ vẽ đường trên bản đồ. Ghi thưa (6h/lần), rolling window 12 điểm/lô (mục 3.1b). Bảng **tách riêng** khỏi vị trí hiện tại trên `shipments`.

| Cột | Kiểu | Ghi chú |
|---|---|---|
| `id` | serial PK | |
| `shipment_id` | int FK | |
| `lat` / `lon` | double precision | |
| `sog` | double precision | Tốc độ tại điểm đó |
| `recorded_at` | timestamptz | Chỉ ghi khi cách điểm gần nhất ≥ 6 giờ |

### 4.4 Bảng `agent_proposals` — đề xuất chờ duyệt (email agent, human-in-the-loop)

Email Agent ghi vào đây ở trạng thái `pending`; người dùng duyệt trên frontend. Agent KHÔNG bao giờ sửa thẳng `shipments` — `approved` → cập nhật `shipments` là hành động do NGƯỜI thực hiện.

| Cột | Kiểu | Ghi chú |
|---|---|---|
| `id` | serial PK | |
| `shipment_id` | int FK null | Có thể null nếu mail chỉ nhắc 1 container và không map được vào lô nào (khác với trường hợp mail nhiều container: container lạ trong đó bị bỏ qua hoàn toàn, không tạo dòng — xem §7.1, v0.9.6) |
| `source_email_id` | text | ID/message-id email nguồn, để trace |
| `extracted_json` | jsonb | `{containers, from_voyage, to_voyage, new_eta, new_vessel_name, reason}` — dữ liệu Agent trích xuất; field chuẩn `containers` theo IC§4.2 |
| `proposed_action` | text | Mô tả hành động đề xuất (VD "dời ETA lô X từ ... sang ...") |
| `status` | text/enum | `pending` \| `approved` \| `rejected` |
| `decided_by` | int FK null | **Ai duyệt/từ chối** — FK `users.id` (mục 4.7). Null khi còn `pending`. Cùng `decided_at` → trace *ai* quyết *khi nào* |
| `created_at` / `decided_at` | timestamptz | |

### 4.5 Bảng `research_findings` — kết quả research (advisory, cần xác minh)

Log kết quả research. Giống `agent_proposals`: đây là log tham khảo, KHÔNG phải nguồn cập nhật `eta_current` trực tiếp. Còn là bằng chứng cụ thể để phân tích đúng/sai của research ở mục 3.3.3 bài luận.

| Cột | Kiểu | Ghi chú |
|---|---|---|
| `id` | serial PK | |
| `shipment_id` | int FK | |
| `route_key` | text | Khóa tuyến để cache (mục 6.3d), VD `SGSIN-VNCLI` |
| `event` | text | Mô tả sự kiện phát hiện (VD "bão nhiệt đới X") |
| `relevance` | text/enum | `cao` \| `trung_binh` \| `thap` (DB không dấu; UI hiển thị có dấu — IC§1.1) |
| `route_impact` | text | Mô tả ảnh hưởng tới tuyến (do research tự sinh) |
| `confidence` | text/enum | `cao` \| `trung_binh` \| `thap` (DB không dấu; UI hiển thị có dấu — IC§1.1) |
| `sources` | jsonb | Danh sách nguồn/URL dùng để kết luận |
| `verified` | boolean | Người dùng đã xác nhận tin này đúng/liên quan chưa (mặc định false) |
| `verified_by` | int FK null | **Ai xác minh** — FK `users.id` (mục 4.7). Null khi chưa ai xác minh. Cùng `verified` → trace *ai* xác nhận tin này |
| `created_at` | timestamptz | |

### 4.6 Bảng `vessel_registry` — cache phân giải định danh tàu

Cache kết quả tra IMO/MMSI của IMO Resolver (mục 6.7a). Định danh tàu (IMO) **không đổi theo đời tàu**, nên một khi đã phân giải thì lưu lại, lô sau cùng tên tàu **dùng lại ngay**, không scrape lại VesselFinder → tiết kiệm thời gian + giảm rủi ro bị chặn bot.

| Cột | Kiểu | Ghi chú |
|---|---|---|
| `id` | serial PK | |
| `vessel_name` | text | Tên tàu (chuẩn hóa: trim, uppercase) — khóa tra |
| `imo` | text | IMO number phân giải được |
| `mmsi` | text null | MMSI (nếu lấy được cùng lúc; có thể điền sau từ AIS static message) |
| `resolved_via` | text/enum | `manual` \| `ais_static` \| `vesselfinder` — nguồn phân giải (để trace độ tin cậy) |
| `resolved_at` | timestamptz | Thời điểm phân giải |

> Lưu ý: tra theo `vessel_name` có thể **trùng tên** (nhiều tàu cùng tên). IMO Resolver dùng thêm `voyage_no` (và POL/POD nếu cần) để phân định khi tra trên VesselFinder trước khi ghi vào registry (mục 6.7a). Khi lấy từ cache, nếu một tên tàu ứng với nhiều IMO thì coi như cache-miss cho lô đó → chạy lại IMO Resolver với đủ ngữ cảnh voyage.

### 4.7 Bảng `users` — người dùng hệ thống (định danh cho audit trail)

Thêm ở v0.8. Lý do có bảng này **không phải chỉ để đăng nhập** mà để **đóng khung audit trail**: mọi hành động do người thực hiện (duyệt `agent_proposals`, xác minh `research_findings`, bấm retry/nhập tay IMO ở onboarding) đều phải trace được về *một người cụ thể* — đúng mục tiêu "mọi thao tác truy vết được" ở checklist 11b. Không quản lý mật khẩu (xác thực qua Google/Microsoft OIDC — mục 3.8), nên **không có cột `password`**.

| Cột | Kiểu | Ghi chú |
|---|---|---|
| `id` | serial PK | |
| `email` | text | Định danh đăng nhập hiển thị (lấy từ id_token của provider). **KHÔNG unique đơn lẻ** — email có thể đổi; khóa đối chiếu là cặp `(provider, provider_sub)` |
| `name` | text | Tên hiển thị (từ provider profile) |
| `provider` | text/enum | `google` \| `microsoft` — provider OIDC đã dùng |
| `provider_sub` | text | `sub` claim từ provider — ID ổn định, **không đổi dù user đổi email hiển thị**; khóa đối chiếu đáng tin hơn email |
| `role` | text/enum | `user` \| `admin` — mặc định `user` khi tạo mới |
| `last_login_at` | timestamptz null | Cập nhật mỗi lần đăng nhập thành công |
| `created_at` | timestamptz | |

> `provider_sub` + `provider` là cặp định danh bền vững nhất (email có thể đổi). **Ràng buộc `UNIQUE (provider, provider_sub)`** (không phải unique trên `email` đơn lẻ — sửa từ v0.9): cùng một `sub` ở hai provider khác nhau là hai người khác nhau, nên khóa duy nhất phải là cặp. Đối chiếu user theo cặp này; `email` chỉ để hiển thị + tra nhanh. Ở MVP hiện **mở đăng ký cho mọi tài khoản Google/Microsoft** (user mới tự tạo, role `user`) — rủi ro này ghi rõ ở mục 9, cần siết bằng whitelist domain khi lên production.

### 4.8 Bảng `shipment_legs` — các chặng/tàu của một lô theo thời gian (v0.9)

Thêm ở v0.9 để vá giả định "1 lô = 1 tàu cố định". Một lô có thể đi **nhiều chặng** (transit qua cảng chuyển tải) hoặc **đổi tàu giữa đường** (rollover). Mỗi chặng/tàu là một dòng ở đây. Đây là **nguồn sự thật** về định danh tàu; các cột tương ứng trên `shipments` (mục 4.1) chỉ là **bản mirror của leg đang active**.

| Cột | Kiểu | Ghi chú |
|---|---|---|
| `id` | serial PK | |
| `shipment_id` | int FK | Trỏ về `shipments.id` |
| `leg_no` | int | Thứ tự chặng (1, 2, 3...). **Rollover ghi cùng `leg_no`** (thay tàu trong cùng chặng), transit dùng `leg_no` tăng dần (chặng kế tiếp) |
| `vessel_name` | text | Tên tàu của chặng này |
| `voyage_no` | text null | Số chuyến chặng này (phân định trùng tên khi tra IMO) |
| `imo` | text null | IMO tàu chặng này — do IMO Resolver (6.7a) phân giải. Null tới khi resolved |
| `mmsi` | text null | MMSI chặng này — khóa AIS subscribe khi chặng này active |
| `imo_resolved_via` | text/enum null | `cache_hit` \| `deterministic_scrape` \| `manual` — nguồn IMO của chặng này (cùng enum như `shipments`) |
| `pol` | text | Cảng xếp của chặng này (khác tổng POL của lô — VD chặng 2 xuất phát từ cảng chuyển tải) |
| `pod` | text | Cảng dỡ của chặng này (VD chặng 1 kết thúc ở cảng chuyển tải, không phải POD cuối) |
| `onboarding_status` | text/enum | **Cổng trạng thái RIÊNG chặng:** `pending` → `resolved` \| `manual_required`. Chặng sau có thể `pending` trong khi chặng trước đã `resolved` + active |
| `onboarding_error` | text null | Lý do fail của chặng này (như `shipments.onboarding_error`) |
| `is_active_leg` | boolean | **Chỉ 1 chặng `true` mỗi lô tại một thời điểm** — chặng tàu đang chở hàng lúc này. AIS worker subscribe theo MMSI của chặng active. Chuyển bằng tín hiệu kép (mục 6.8) |
| `superseded_at` | timestamptz null | Set = `now()` khi dòng này bị thay bởi rollover (tàu mới cùng `leg_no`). Null = còn hiệu lực. Giữ dòng cũ để trace lịch sử đổi tàu |
| `created_at` | timestamptz | |

> **Lô `direct` cũng tạo đúng 1 dòng** `leg_no=1`, `is_active_leg=true`, `pol/pod` = POL/POD của lô. Không rẽ nhánh code: AIS worker và onboarding đi **cùng một đường** cho cả direct lẫn transit — direct chỉ là trường hợp "1 leg". Điều này giữ code đơn giản (không có 2 nhánh xử lý riêng).
>
> **Quan hệ mirror với `shipments` (mục 4.1):** khi một leg là `is_active_leg=true`, các cột `imo/mmsi/imo_resolved_via/onboarding_status/onboarding_error` của nó được **sao xuống** `shipments` cùng tên cột, qua hàm `resolve_leg()` trong CÙNG 1 transaction (mục 6.7a). Nhờ vậy AIS worker + Agent A/B **đọc thẳng `shipments` như cũ, KHÔNG cần JOIN, KHÔNG đổi code** — chỉ có lớp ghi (onboarding + switch leg + rollover) là biết tới `shipment_legs`. "1 nguồn ghi, 2 nơi đọc."

### 4.9 Chính sách dọn dữ liệu (retention)

- Khi `shipments.status` chuyển sang `delivered`, hệ thống **không xóa ngay** — đánh dấu `delivered_at` và giữ nguyên `vessel_trail` + `eta_history` (+ `research_findings`) liên quan thêm **14 ngày**.
- Sau 14 ngày kể từ `delivered_at`, một cleanup job (chạy 1 lần/ngày) xóa dữ liệu chuỗi thời gian của lô đó. Bảng `shipments` giữ lại (bản ghi lô vẫn có giá trị tra cứu), chỉ dọn dữ liệu chi tiết theo thời gian.
- **Lưu ý khi làm bài luận:** 14 ngày có thể ngắn hơn thời gian cần để viết Chương 3 (mục 3.3.2/3.3.3 cần ảnh chụp, biểu đồ ETA thực tế). Nên chủ động **export CSV hoặc chụp màn hình các lô demo tiêu biểu ngay sau khi hoàn tất vòng đời** (giao hàng), đừng để cleanup job tự xóa mất bằng chứng.
- Việc tự dọn dữ liệu sau một khoảng giữ lại (thay vì xóa ngay hoặc giữ vĩnh viễn) là quyết định đáng nêu trong bài luận: thể hiện tư duy vận hành thực tế (data lifecycle), không chỉ "chạy demo được".

---

## 5. Incoterm × Chiều giao dịch — logic điều hướng (điểm nghiệp vụ cốt lõi)

Nguyên tắc: **ai kiểm soát chặng vận chuyển chính (main carriage) thì người đó làm việc với hãng tàu và nhận thông báo.** Incoterm quyết định *ai* lo main carriage (bên mua hay bên bán), nhưng **U&I có thể là bên mua (hàng nhập) hoặc bên bán (hàng xuất)** — nên phải kết hợp Incoterm **VỚI chiều giao dịch** (`shipment_direction`) mới xác định được liệu U&I có đang kiểm soát main carriage hay không. Đây là insight nghiệp vụ cốt lõi, nên trình bày kỹ trong bài luận mục 3.2.2.

**[v0.9.8 — ĐÃ XÁC NHẬN với công ty]** Trước đây spec chỉ tính hàng nhập (ngầm định U&I luôn là bên mua). Thực tế U&I còn có giao dịch **xuất C/D**, ở đó U&I là bên bán và **book tàu + nhận mail hãng tàu trực tiếp** — giống bản chất kiểm soát như nhập E/F. **Xuất E/F ngoài phạm vi** (buyer nước ngoài lo main carriage, U&I không kiểm soát được luồng mail).

| Direction | Nhóm | Incoterm | Ai lo main carriage | U&I có kiểm soát + nhận notify hãng tàu trực tiếp? | `monitoring_mode` |
|---|---|---|---|---|---|
| Nhập | E | EXW | Người mua = **U&I** (→ 3PL đại diện) | Có (U&I book tàu) | `auto_email` |
| Nhập | F | FCA, FAS, FOB | Người mua = **U&I** | Có | `auto_email` |
| Nhập | C | CFR, CIF, CPT, CIP | Người bán (nước ngoài) | Không trực tiếp (qua người bán/đại lý) | `manual` |
| Nhập | D | DAP, DPU, DDP | Người bán (nước ngoài) | Không trực tiếp | `manual` |
| **Xuất** | **C** | **CFR, CIF, CPT, CIP** | **Người bán = U&I** | **Có (U&I book tàu) — [v0.9.8 MỚI]** | **`auto_email`** |
| **Xuất** | **D** | **DAP, DPU, DDP** | **Người bán = U&I** | **Có — [v0.9.8 MỚI]** | **`auto_email`** |
| Xuất | E/F | EXW, FCA, FAS, FOB | Người mua (nước ngoài) | Không — U&I không kiểm soát | **[v0.9.8] Không hỗ trợ — ẩn khỏi dropdown Incoterm khi chọn `shipment_direction = export`** |

**Hệ quả thiết kế:** khi tạo lô, user chọn `shipment_direction` (nhập/xuất) **trước**, dropdown Incoterm lọc theo direction đó (xuất → chỉ hiện nhóm C/D, ẩn E/F). Chọn xong cặp `(direction, incoterm)` → hệ thống tự set `monitoring_mode` theo bảng trên. Trên UI:
- Lô `auto_email` (nhập E/F **hoặc xuất C/D**): huy hiệu "🟢 Agent giám sát hộp thư + auto-forward". Mail hãng tàu tới thẳng hộp delegate (hoặc auto-forward mức server) → Agent đọc + trích xuất + được phép **auto-forward** tới whitelist nội bộ (§7.4).
- Lô `manual` (chỉ còn nhập C/D): huy hiệu "⚪ Agent đọc, forward thủ công". Vẫn tracking AIS bình thường (AIS không phụ thuộc Incoterm/direction — chỉ cần biết tàu là theo dõi được). Mail transit C/D CÓ THỂ và THỰC SỰ đi tới mailbox hệ thống (qua nhiều bước tay hơn lô `auto_email`); **khi tới nơi, Agent vẫn ĐỌC + trích xuất + tạo `agent_proposals` như lô `auto_email`** — chỉ khác là **không auto-forward** (người dùng tự quyết chuyển tiếp).

> **[v0.9.7 — chốt ngữ nghĩa `monitoring_mode`]** Trường này quyết định **luồng FORWARD** (auto vs tay), **KHÔNG** quyết định việc Agent đọc/đề xuất. Agent đọc & tạo proposal cho **mọi mail hợp lệ** vào hộp delegate, bất kể mode (mail hợp lệ = qua một trong hai allowlist ở §7.4). Lý do tách bạch: mục §5 [ĐÃ XÁC MINH] xác nhận mail C/D nhập *thực sự* tới được hộp hệ thống — nếu để `manual` chặn luôn việc đọc thì mail đó thành "mail mồ côi" (tới nơi nhưng không ai trích xuất), phí đúng cái luồng vừa xác minh. `manual` chỉ nói "không tự động forward", không nói "không đọc". **[v0.9.8]** Kết luận này không đổi khi thêm chiều xuất — nó vốn viết theo `monitoring_mode` (đã suy 2 chiều), không theo nhóm chữ cái, nên "chịu được" việc thêm case xuất C/D mà không cần sửa.

> **[ĐÃ XÁC MINH với U&I]** Với **nhập** C/D, hãng tàu chỉ làm việc và thông báo cho bên book tàu (người bán, nước ngoài) về việc chuyển tàu/transit; Đại lí đầu xuất có nhiệm vụ forward mail cho bên mình rồi cần user phải manual forward qua cho mail của hệ thống — mail transit của nhập C/D CÓ THỂ và THỰC SỰ đi tới được mailbox hệ thống, chỉ là qua nhiều bước tay hơn E/F. Để MVP an toàn, mặc định nhập C/D = `manual`.

> **[ĐÃ XÁC NHẬN với công ty, v0.9.8]** Với **xuất** C/D, U&I là bên bán book tàu → hãng tàu làm việc và thông báo **trực tiếp** cho U&I, giống hệt cơ chế nhập E/F (không qua trung gian, không cần forward tay). Do đó xuất C/D = `auto_email`.

---

## 6. Module 1 — Tracking + ETA động

### 6.1 Milestone (cột mốc trên progress bar)

Progress bar hiển thị các cột mốc, giống theo dõi đơn TMĐT:
```
[Nhận B/L] → [Tàu khởi hành ATD] → [Đang trên biển] → [Transit*] → [Cập cảng đích ETA] → [Giao hàng]
```
(*Transit chỉ hiện nếu lô có chuyển tải.) **[v0.9.10]** Milestone là **lớp hiển thị suy diễn** từ tổ hợp `(status, atd IS NULL, shipment_type, is_active_leg)` — `status` chỉ có 4 giá trị (§4.1); 6 node trên là cách trình bày UI, KHÔNG phải mỗi node một giá trị enum riêng. Công thức map đầy đủ: **Interface-Contract IC§1.2** (nguồn chân lý, không lặp lại ở đây). *(Câu cũ "Mỗi cột mốc là một `status` trong `shipments`" đã bỏ — mâu thuẫn với §4.1, xem changelog v0.9.10.)* Node hiện tại nhấp nháy; ETA hiển thị **động** cạnh node đích và **đổi màu khi lệch quá ngưỡng**.

> **Transit — chi tiết ở v0.9 (mục 6.8, [STRETCH]):** node `[Transit]` chỉ hiện khi `shipments.shipment_type = transit`. Với lô transit, có thể hiển thị **từng chặng** (leg) trong `shipment_legs` — cảng chuyển tải trung gian, tàu của mỗi chặng, và **chặng nào đang active** (đang chở hàng, AIS đang theo dõi). Rollover (đổi tàu giữa chừng) không tạo node mới trên progress bar — chỉ đổi tên tàu của chặng hiện tại (dòng cũ giữ lại với `superseded_at` để trace). Lô `direct` (cả 2 tuyến demo — nhập lẫn xuất, mục 1.4) không có node này.

### 6.2 Nguồn dữ liệu và tần suất (khớp free tier)

| Dữ liệu | Nguồn | Cách lấy | Tần suất + ràng buộc free tier |
|---|---|---|---|
| Vị trí, SOG, COG tàu | aisstream.io (live) / fixture PositionReport (replay) | `AIS_MODE=live`: **WebSocket** subscribe theo MMSI/bounding box, realtime; `AIS_MODE=replay`: đọc fixture JSON và bơm vào cùng parser/upsert — mục 3.1 | Live: free, cần key, gần bờ ổn hơn. Replay: không key/tàu thật, deterministic cho test/CI/TASK-17 |
| Thời tiết, sóng, gió | Open-Meteo Marine API | REST GET định kỳ | Free, **không cần API key**, 3-6h/lần |
| **Dòng chảy, hướng dòng** | **Open-Meteo Marine API** | **REST GET — thêm 2 tham số `ocean_current_velocity`, `ocean_current_direction` vào chính lệnh gọi wind/wave đang có (mục 6.3), không phát sinh call riêng** | **[v0.9.9]** Free, **không cần API key, không giới hạn call/ngày** — dữ liệu từ mô hình Copernicus Marine/MeteoFrance. **Trước v0.9.9 lấy từ Stormglass (10 call/ngày); nay chuyển sang Open-Meteo → giải phóng toàn bộ quota Stormglass cho thủy triều** |
| **Thủy triều cảng đích (UKC/tidal window)** | **Stormglass.io — `GET /v2/tide/extremes/point?lat=&lng=`** (hoặc `sea-level/point` nếu cần đường cong mực nước theo giờ) | **REST GET, cron 12h/lần (2 lần/ngày), chỉ lô "đang trên biển". Truyền `lat`/`lng` cảng đích (geocode từ tên cảng qua World Port Index, mục 6.6); StormGlass tự chọn trạm đo gần nhất + trả metadata tên trạm + khoảng cách** | **[v0.9.9]** Free tier **10 call/ngày**. Tính: **~5 lô × 2 call/ngày = 10 call/ngày** = vừa khít quota (**cùng công thức cũ, nay dành cho thủy triều thay vì dòng chảy**). Không cần gói $19 cho demo (ghi roadmap production, mục 10) |
| ETA gốc | Carrier ETA lookup (mục 6.7b) / Booking Confirmation / B/L | Agentic browser qua Playwright MCP; fallback nhập tay | Giới hạn 2-3 hãng demo; nhập tay khi scrape fail (mục 6.7b) |
| IMO/MMSI (định danh tàu) | VesselFinder (mục 6.7a) | IMO Resolver — script Playwright cứng (KHÔNG LLM/MCP) tra từ Vessel Name + Voyage; cache `vessel_registry` | Chạy 1 lần/lô qua HTTP job-queue; fallback nhập tay khi bị chặn (mục 6.7a) |

Số lô theo dõi đồng thời **~3-5 lô** được chọn để khớp free tier Stormglass ở trên — đây là ràng buộc kỹ thuật đáng nêu trong bài luận (thiết kế quy mô demo bám sát giới hạn tài nguyên miễn phí). **[v0.9.9]** Lưu ý: quota Stormglass giờ dành cho **thủy triều** (trước đây dành cho dòng chảy); dòng chảy đã chuyển sang Open-Meteo miễn phí không giới hạn, nên không còn cạnh tranh quota.

### 6.3 ETA Engine — HAI TẦNG rule-based

Đây là phần cốt lõi, cần trình bày cẩn thận để phòng thủ tốt. **Cả hai tầng đều là công thức trong code, đều truy vết được.** Không ML, không "hộp đen".

**Tầng 1 — Động học thuần (kinematics):**
```
1. Lấy vị trí hiện tại (lat/lon) từ AIS
2. Tính khoảng cách còn lại tới POD (haversine — **[v0.9.12] xấp xỉ great-circle, KHÔNG phải route distance thực tế** theo luồng hàng hải/eo/kênh; hoặc theo waypoint tuyến nếu muốn chính xác hơn). Nêu đúng nhãn này khi bảo vệ/viết essay để không overclaim độ chính xác khoảng cách.
3. Tốc độ trung bình trượt (trung bình SOG của 6-12 bản tin gần nhất, lọc nhiễu)
3b. **[v0.9.6] Guard ngưỡng SOG tối thiểu:** nếu tốc_độ_trung_bình < `SOG_MIN_KNOT` (tham số config, VD 1-2 hải lý/giờ — tàu đang neo chờ/cập cảng/chuyển tải) → **KHÔNG tính lại ETA cho vòng này**, giữ nguyên `eta_current` (Tầng 1 + Tầng 2) **và giữ nguyên trạng thái cảnh báo lệch** của lần tính gần nhất, bỏ qua **bước 4-11** bên dưới (cả khối tính ETA lẫn khối cảnh báo 9b-11). Lý do: chia khoảng_cách_còn_lại cho tốc độ ≈ 0 khiến ETA nhảy tới giá trị cực lớn/loạn ở mỗi lần tính lại, phá vỡ tính ổn định của progress bar; đồng thời "tàu đang neo" không có nghĩa là "sắp tới nơi". Khi SOG vượt lại ngưỡng ở vòng tính sau, tính lại bình thường.
4. ETA_tầng1 = now + (khoảng_cách_còn_lại / tốc_độ_trung_bình)  *(chỉ chạy khi qua được guard 3b)*
```
Tầng 1 trả lời: "với tốc độ hiện tại, tàu tới cảng lúc nào." Đơn giản, minh bạch, nhưng bỏ qua điều kiện biển.

**Tầng 2 — Điều chỉnh theo môi trường (rule-based, hệ số config):**
```
5. Lấy wind_speed, wave_height + current_speed (ocean_current_velocity),
   current_direction (ocean_current_direction) — TẤT CẢ từ MỘT lệnh gọi Open-Meteo Marine
   (mục 6.2, v0.9.9) tại vị trí/tuyến hiện tại của tàu
6. So current_direction với hướng đi thực tế (COG) → cùng dòng hay ngược dòng.
   **[v0.9.12] Wrap-around 0/360 BẮT BUỘC:** góc lệch = `delta = min(|current_direction − COG|, 360 − |current_direction − COG|)`
   (VD COG 359° vs dòng 1° → lệch 2°, KHÔNG phải 358°). Dựa trên `delta` để phân loại cùng/ngược dòng
   (VD delta gần 180° = ngược dòng, gần 0° = cùng dòng). Tính sai wrap-around ở biên 0/360 sẽ đảo ngược
   phân loại cùng/ngược dòng → sai hệ số Tầng 2.
7. Áp hệ số điều chỉnh tốc độ hiệu dụng theo config, ví dụ:
   - Ngược dòng > X hải lý/giờ → giảm tốc độ hiệu dụng Y%
   - Gió giật > Z hải lý/giờ (ngược hướng) → giảm thêm W%
   - Cùng dòng → cộng nhẹ, hoặc bỏ qua nếu muốn thiên an toàn (dự phòng trễ hơn là sớm)
8. tốc_độ_hiệu_dụng = tốc_độ_trung_bình × hệ_số_điều_chỉnh
9. ETA_tầng2 = now + (khoảng_cách_còn_lại / tốc_độ_hiệu_dụng)
```
**Con số ETA chính thức ghi vào `eta_history` (source = `weather_adjusted`) và hiển thị trên progress bar là kết quả Tầng 2** — thay cho ETA_tầng1 thô.

> Các hệ số `X, Y, Z, W` **và `SOG_MIN_KNOT` (ngưỡng SOG tối thiểu, v0.9.6)** là **tham số config** (không hardcode trong logic), để tinh chỉnh sau khi quan sát dữ liệu thật mà không phải sửa code. Ghi rõ giá trị đã chọn cho demo vào **phụ lục bài luận**, kèm lý do (tham khảo tài liệu hàng hải, hoặc ước lượng hợp lý cho MVP).

**Kích hoạt cảnh báo:**
```
9b. [v0.9.6] Guard trước khi tính deviation: chỉ chạy bước 10 khi `atd` khác null VÀ `eta_original > atd`.
    Nếu chưa thỏa (tàu chưa khởi hành, hoặc dữ liệu nhập tay bẩn khiến eta_original ≤ atd)
    → bỏ qua bước 10-11 cho lần tính này: ETA vẫn hiển thị bình thường từ Tầng 2,
    chỉ riêng phần "cảnh báo % lệch" tạm ẩn. Không ghi onboarding_error (đây là trạng thái
    bình thường trước khi tàu khởi hành, không phải lỗi).
10. deviation_pct = (ETA_tầng2 − ETA_gốc) / (ETA_gốc − ATD)
    **[v0.9.12] Chốt DẤU tường minh:** dương = tàu **TRỄ** (ETA_tầng2 muộn hơn ETA_gốc), âm = **SỚM**.
    Toàn bộ tính bằng epoch/UTC (IC§15) — cả tử số lẫn mẫu số là hiệu thời gian tính bằng giây/epoch.
11. Nếu |deviation_pct| ≥ ngưỡng (VD 10%) → đổi màu ETA + ghi eta_history + đẩy WebSocket lên frontend
    (kích alert theo TRỊ TUYỆT ĐỐI — cả trễ lẫn sớm quá ngưỡng đều cảnh báo).
```
> **[v0.9.6]** Lý do cần guard 9b: mẫu số `(ETA_gốc − ATD)` bằng 0 hoặc âm khi chưa có `atd` hợp lệ → `deviation_pct` vô nghĩa hoặc lỗi chia 0, có thể kích cảnh báo sai ngay từ khi lô mới tạo (trước khi tàu khởi hành).

> Ngôn ngữ trình bày: luôn gọi là **"cảnh báo biến động/độ trễ"**, KHÔNG gọi "dự báo chính xác". Đây là ước lượng dựa trên tốc độ hiện tại + điều kiện biển, không tính hết yếu tố cảng/thủy triều/xếp dỡ — sự khiêm tốn này là điểm phòng thủ khi bảo vệ.

**Vì sao tách 2 tầng (điểm phòng thủ):** cho phép giải thích rành mạch với hội đồng — Tầng 1 là "toán thuần", Tầng 2 là "hiệu chỉnh theo điều kiện thực tế bằng hệ số minh bạch". Hội đồng hỏi "tại sao ETA đổi" → luôn chỉ ra được nguyên nhân (tốc độ giảm, gió ngược, hay dòng chảy) — khác hẳn ML hộp đen.

### 6.3b Vai trò của Agent A — ETA Reasoning Agent (Layer 3) — điều phối + diễn giải, KHÔNG quyết con số

Chỗ dễ hiểu lầm nhất, cần chốt rõ. **Agent A (ETA Reasoning Agent, chạy trên AG2)** nhận toàn bộ dữ liệu từ tool Layer 2 (vị trí, tốc độ, thời tiết, dòng chảy, và ETA_tầng2 đã tính ở 6.3) và đóng vai trò:

1. **Điều phối (orchestration):** quyết định gọi tool nào (lô đã có vị trí mới chưa, có cần kiểm tra thời tiết/dòng chảy trước khi tính lại không) qua function-calling của AG2, rồi kích ETA Engine.
2. **Phối hợp với Agent B (Research)** để kiểm tra tín hiệu khó rule-hóa (tin bão, sự kiện ảnh hưởng tuyến) — Agent A đánh giá kết quả của Agent B, nếu chưa đủ thì yêu cầu B search lại theo hướng cụ thể (vòng lặp A↔B) — mục 6.3c.
3. **Tổng hợp + diễn giải (interpretation):** đọc kết quả 2 tầng ETA + thời tiết/dòng chảy + kết quả research từ Agent B → sinh **nhận định chuyên gia định tính** bằng ngôn ngữ tự nhiên, hiển thị *cạnh* (không đè lên) con số baseline. Ví dụ: *"ETA đã điều chỉnh dời thêm 3h do dòng chảy ngược. Research phát hiện tin bão nhiệt đới có thể ảnh hưởng eo biển trên tuyến trong 24-48h tới — độ tin cậy trung bình, cần theo dõi sát."*

**Con số ETA chính thức luôn là kết quả công thức rule-based (Tầng 1 + Tầng 2)** — KHÔNG do Agent A hay Agent B tự suy ra. Lý do giữ ranh giới này: bài luận đã chốt "không ML vì ngoài phạm vi học kỳ, ưu tiên rule-based vì dễ giải thích/truy vết" — nếu để LLM tự quyết con số ETA, ranh giới đó bị xoá nhoà, khó trả lời khi hội đồng hỏi "vậy khác gì ML dự đoán ETA?". Cách trình bày: **"con số do rule quyết, lời do agent nói"** — người dùng thấy cả số (đáng tin, truy vết được) lẫn lời giải thích (dễ hiểu, chủ động).

### 6.3c Agent B — Research Agent (Core) — chạy trên AG2

**Mục tiêu:** phát hiện sự kiện khó rule-hóa nhưng ảnh hưởng tuyến/ETA — bão, xung đột/chiến sự khu vực, tắc nghẽn cảng, sự cố kênh đào/eo biển... — những thứ không thể viết công thức số như Tầng 2.

**Cách hiện thực (nhất quán với mục 3.5):** research là **Agent B**, một agent AG2 riêng có tool web search. Agent A gọi B, B tự chạy vòng lặp tool-calling (do AG2 lo phần retry/điều phối lượt) rồi trả kết quả về cho A đánh giá:
```
Agent A gọi Agent B (kèm context: pol, pod, tuyến, khung thời gian ETA hiện tại)
   → Agent B + tool web search: tìm tin liên quan
   → Agent B tự đánh giá: tin có thật sự liên quan tuyến/khung thời gian không?
     → Nếu chưa chắc, search lại với từ khóa khác (AG2 lo vòng lặp tool-calling + retry;
       giới hạn tối đa N vòng, VD 3, tránh lặp vô hạn)
   → Trả kết quả dạng Pydantic model: {event, relevance, route_impact, confidence, sources}
     (JSON mode + Model.model_validate_json + retry 1 lần nếu sai format)
   → Agent A nhận, ĐÁNH GIÁ: nếu chưa đủ/mơ hồ → yêu cầu B search lại theo hướng cụ thể
     (vòng lặp A↔B); nếu đủ → đưa vào nhận định chuyên gia (6.3b) — LUÔN gắn nhãn
     "cần xác minh", KHÔNG tự sửa eta_current
```

**Nguyên tắc an toàn (giống Email Agent, mục 7.2):**
- Research chỉ là nguồn tín hiệu **tham khảo** — kết quả có thể sai (tin không liên quan, tin cũ, false positive từ search). Mọi phát hiện hiển thị dạng "⚠️ cần xác minh", **không bao giờ tự động thay đổi `eta_current`**.
- Giới hạn số vòng search (VD tối đa 3 vòng/lần hỏi) để tránh lặp vô hạn hoặc tốn quá nhiều token/call.

**Cadence gọi research:** không gọi Agent B mỗi lần Agent A chạy — theo chu kỳ định kỳ tương tự Stormglass (VD 1-2 lần/ngày/lô đang trên biển), để kiểm soát chi phí search API (Tavily/Serper/Brave — chọn cụ thể lúc build, không phải web_search miễn phí không giới hạn).

**Ghi log:** mỗi kết quả research lưu vào `research_findings` (mục 4.5) — vừa hiển thị lịch sử, vừa làm bằng chứng cụ thể cho mục 3.3.2/3.3.3 bài luận (chụp lại một case research phát hiện đúng/sai để phân tích).

### 6.3d Cache kết quả research theo tuyến

Ở quy mô 3-5 lô, nhiều khả năng vài lô đi **cùng tuyến** (Singapore/HK/Kaohsiung → Cát Lái). Nếu 3 lô cùng tuyến mà research search riêng cho từng lô thì lãng phí quota vào cùng một câu hỏi. Vì vậy:

- **Cache kết quả theo `(route_key, khung_thời_gian)`** với TTL trùng cadence (VD 12h). `route_key` = cặp POL-POD chuẩn hóa (VD `SGSIN-VNCLI`).
- Các lô cùng `route_key` trong cùng khung TTL **dùng lại** kết quả research đã có, không search lại.
- Đây là **hệ quả tự nhiên** của đúng ràng buộc rate-limit đã tự đặt ra (mục 6.2), nên thêm vào ngay từ MVP — KHÔNG phải over-engineering.
- Hiện thực đơn giản: một bảng cache trong Postgres (hoặc Redis nếu đã có), key = `route_key + bucket thời gian`, value = kết quả research + timestamp.

> **KHÔNG làm ở MVP (đẩy future work, mục 10):** pattern **vote / team-leader** (nhiều agent research độc lập rồi tổng hợp bằng leader) là over-engineering ở quy mô 3-5 lô, 1 loại câu hỏi. Chỉ có giá trị khi cần tăng độ tin cậy ở quy mô lớn hoặc nhiều loại quyết định.

### 6.4 Agent invocation gần stateless

Mỗi lần gọi Agent A cho 1 lô: **nạp state mới nhất của lô đó từ DB** (vị trí, ETA 2 tầng, thời tiết, research cache) → xử lý (kể cả vòng A↔B với Agent B nếu cần) → ghi kết quả → kết thúc. **Không tích lũy transcript hội thoại cũ** giữa các lần gọi (mỗi lần chạy AG2 khởi tạo lại từ state DB).

Lý do: ở quy mô nhỏ (3-5 lô), tích lũy lịch sử hội thoại giữa các lần chạy chỉ làm phình context, tăng chi phí token, không thêm giá trị. `shipment_id` là **khóa để trace** (tra `eta_history`, `agent_proposals`, `research_findings`), không phải context tích lũy trong đầu agent. Đây là lý do dùng AG2 để lo vòng lặp tool-calling + retry + điều phối 2 agent *trong một lần chạy*, nhưng KHÔNG dựa vào bộ nhớ hội thoại dài hạn của framework giữa các lần chạy — chọn đúng độ phức tạp cho quy mô (song song với quyết định "không Kafka").

### 6.5 Cảnh báo bão — kết hợp ngưỡng + tin tức

Hai nguồn tín hiệu:
1. **Ngưỡng gió/sóng (rule, từ Open-Meteo):** nếu gió/sóng tại vùng tàu vượt ngưỡng config (VD sóng > 3m, gió > cấp 7) → gắn cờ "điều kiện biển xấu" → Tầng 2 tự giảm tốc độ hiệu dụng + Agent A nêu trong nhận định. Đây là phần **cam kết cứng** (đã có sẵn dữ liệu Open-Meteo).
2. **Tin tức bão/sự kiện (research, mục 6.3c — Core):** loại tín hiệu không rule-hóa được (bão đang hình thành ngoài dự báo điểm, cấm biển, xung đột trên tuyến).

### 6.6 Thủy triều / UKC (tidal window) — **[v0.9.9 VIẾT LẠI: StormGlass tide, bỏ bảng tĩnh]**

Tàu lớn chỉ vào cảng được trong "tidal window" (đủ UKC — Under Keel Clearance). Nếu ETA_tầng2 rơi ngoài cửa sổ thủy triều → cảnh báo "có thể phải chờ con nước". Ở demo chỉ **minh họa khái niệm cảnh báo**, không tính UKC điều hướng thật.

**Nguồn dữ liệu (v0.9.9 — thay bảng thủy triều tĩnh Cát Lái):** dùng **StormGlass** `GET /v2/tide/extremes/point?lat=&lng=` — trả các thời điểm **đỉnh/đáy triều** tại tọa độ cảng đích, phù hợp để so ETA có rơi vào cửa sổ UKC hay không. Nếu cần đường cong mực nước theo từng giờ (10 ngày tới) thì dùng `sea-level/point`. Chỉ cần truyền `lat`/`lng` — **không phải tự tìm trạm đo**: StormGlass tự chọn trạm gần tọa độ nhất trong hệ thống của họ, kèm metadata tên trạm + khoảng cách trong response (đã kiểm chứng tài liệu chính thức). Quota: dùng trọn free tier **10 call/ngày** (~5 lô × 2 lần/ngày, mục 6.2) — trước đây quota này dành cho dòng chảy, nay dòng chảy đã chuyển sang Open-Meteo.

**Geocode tên cảng → tọa độ:** StormGlass nhận `lat`/`lng`, không nhận tên cảng. Dùng **World Port Index (WPI — publication 150 của NGA, >3.700 cảng toàn cầu kèm tọa độ)**: dataset **tĩnh, tải về MỘT LẦN** (CSV/GeoJSON), tra cứu **offline/local** trên server — KHÔNG phải API gọi runtime, nên không thêm điểm phụ thuộc mạng, không tốn quota nào. Với tên cảng không khớp chính xác (viết tắt, tên địa phương) thêm bước fuzzy-match (VD rapidfuzz) hoặc bảng alias thủ công cho các cảng dùng trong demo. Nhờ vậy logic thủy triều **chạy được cho cảng đích bất kỳ** (nhập → cảng VN, xuất → cảng nước ngoài — khớp mở rộng v0.9.8), không còn hardcode riêng Cát Lái.

**Giới hạn PHẢI nêu (chi tiết ở mục 9 — tránh nói quá khi bảo vệ):**
- Mực nước trả về **tương đối theo MSL (Mean Sea Level)**, KHÔNG neo theo **chart datum (LAT)** mà hải đồ dùng để tính UKC thật. Với mức demo "minh họa khái niệm cảnh báo chờ con nước" thì dùng thẳng MSL là đủ; muốn gần thực tế hơn cần 1 hằng số offset chart-datum-to-MSL mỗi cảng (tra 1 lần từ hải đồ — ghi ở mục 10, future work).
- StormGlass **không đảm bảo có trạm nằm sâu trong sông** — với cảng sông như Cát Lái (cách biển ~50km theo sông Sài Gòn), trạm gần nhất khả năng cao nằm ngoài cửa sông, không phản ánh đúng đặc tính triều trong sông.
- **Cách diễn đạt bắt buộc:** việc đổi nguồn này là "**tổng quát hóa nguồn dữ liệu**" (chạy được cho cảng bất kỳ, bỏ hardcode), **KHÔNG phải "chính xác hơn"** tại đúng cảng demo (bảng tĩnh cũ vốn lấy từ hải đồ/Trung tâm Hải văn thật). Nhất quán quy ước mục 6.3: gọi là "cảnh báo/ước lượng", không gọi "dự báo chính xác".

**Fallback (đúng pattern cache đã có cho các nguồn khác):** nếu call StormGlass thất bại hoặc vượt quota → **giữ giá trị cache gần nhất**, gắn nhãn "dữ liệu có thể trễ" trên UI — không cần logic mới, không retry phức tạp.

> **Tier dự phòng (tham khảo):** Tier 1 = StormGlass tide + Open-Meteo current (đường chạy chính MVP, 0 công sức setup); Tier 2 = cache giá trị gần nhất (fallback trên); Tier 3 (tùy chọn, offline hoàn toàn — pyTMD + FES2014/TPXO9) ghi ở mục 10 future work, KHÔNG nằm trong luồng chính của demo.

### 6.7 Onboarding lô hàng — hai thành phần phân giải + cổng trạng thái

Đây là **lớp onboarding** (thêm ở v0.6, tinh chỉnh ở v0.7), chạy **trước** toàn bộ vòng tracking. Lý do phải có: AIS subscribe theo MMSI/IMO, nhưng chứng từ chỉ cho Vessel Name + Voyage → thiếu bước phân giải định danh thì AIS worker không biết subscribe cái gì.

**Thay đổi quan trọng ở v0.7 — tách "Agent C" thành HAI thành phần theo đúng độ phức tạp cần thiết:**

| Thành phần | Bản chất | Vì sao |
|---|---|---|
| **(a) IMO Resolver** (mục 6.7a) | **Script Playwright viết cứng (deterministic), KHÔNG LLM, KHÔNG MCP** | VesselFinder là **1 trang cố định, luồng thao tác y hệt mỗi lần** → cho LLM "click từng bước" chỉ tốn thêm vòng gọi model + kém tin cậy hơn code cứng. Chỉ nhường quyết định cho LLM ở chỗ *thật sự* cần suy luận. |
| **(b) Carrier ETA Agent** (mục 6.7b) | **Agent có LLM, gọi tool trình duyệt qua Playwright MCP (agentic)** | Mỗi hãng tàu một giao diện khác nhau → *đây* mới là chỗ cần LLM tự đọc trang, quyết "ETA nằm ở đâu, click vào đâu". |

> Đây là cùng một nguyên tắc "**đúng độ phức tạp cho đúng việc**" đã dùng cho quyết định không-Kafka và cách dùng AG2: nhường quyền cho LLM ở nơi có suy luận thật (nhiều layout), giữ code cứng ở nơi luồng cố định (một trang). Khi bảo vệ, đây là điểm mạnh — cho thấy biết *khi nào KHÔNG cần* LLM.

**Nguyên tắc điều phối — cổng trạng thái ở DB, KHÔNG dùng handoff hội thoại AG2:**

`shipments.onboarding_status` là cổng chặn thứ tự chạy:
```
Tạo lô mới → onboarding_status = pending
   → (a) IMO Resolver chạy (phân giải IMO/MMSI)  +  (b) Carrier ETA Agent (ETA baseline)
      → có IMO/MMSI → onboarding_status = resolved  → mở khóa AIS worker + Agent A/B
      → thất bại   → onboarding_status = manual_required → chờ người nhập tay / bấm retry
```
- **AIS worker CHỈ subscribe** những lô `resolved` (đã có MMSI/IMO). Lô `pending`/`manual_required` không được đưa vào danh sách subscribe.
- **Agent A/B CHỈ chạy** cho lô `resolved`.
- Điều kiện `resolved` là **có IMO/MMSI** (đầu ra của (a)). Carrier ETA (b) là tiện ích thêm — thiếu nó vẫn `resolved` được (nhập `eta_original` tay), miễn đã có định danh tàu.
- Vì sao dùng state gate ở DB thay vì để AG2 tự handoff: giữ hai thành phần onboarding **tách biệt** (single responsibility, giống cách Email Agent tách qua DB `agent_proposals`), tránh nhét mọi thứ vào một hội thoại AG2 dài. Thứ tự được ép bằng **trạng thái dữ liệu**, dễ trace, dễ retry, không phụ thuộc bộ nhớ hội thoại framework.
- *(Từ v0.9:* `shipments.onboarding_status`/`imo`/`mmsi` nói ở đoạn này là **bản mirror** của `shipment_legs` — chi tiết pattern mirror ở mục 4.8/6.7a. Đoạn nguyên tắc điều phối trên vẫn đúng nguyên vì AIS worker/Agent A/B đọc thẳng `shipments` như mô tả, chỉ khác là nguồn ghi gốc nằm ở `shipment_legs`.)*

#### 6.7a IMO Resolver — script Playwright cứng (deterministic, KHÔNG LLM)

**Mục tiêu:** từ `vessel_name` (+ `voyage_no` để phân định trùng tên) → ra `imo` (và `mmsi` nếu có), ghi vào `shipment_legs` (nguồn sự thật) → mirror lên `shipments` nếu leg đang active + cache `vessel_registry`.

**Chạy trên một `leg` cụ thể (v0.9):** từ v0.9 IMO Resolver luôn nhận vào **`leg_id`** (một dòng trong `shipment_legs`, mục 4.8), không ghi thẳng `shipments` nữa. Lô `direct` có đúng 1 leg (`leg_no=1`, `is_active_leg=true`) nên hành vi y hệt trước; lô `transit` gọi resolver một lần cho mỗi leg. Kết quả ghi qua hàm `resolve_leg()` (bên dưới) để bảo đảm mirror nhất quán.

**Cách hiện thực (Playwright viết cứng — v0.7 đổi từ agentic sang deterministic; v0.9 ghi qua leg):**
```
1. Kiểm cache vessel_registry theo vessel_name (chuẩn hóa).
   - Hit + 1 IMO duy nhất → resolve_leg(leg_id, imo, mmsi, 'cache_hit'). XONG (không chạm web).
   - Miss / nhiều IMO trùng tên → sang bước 2.
2. Script Playwright mở VesselFinder, điền vessel_name vào ô tìm, đọc bảng kết quả
   (selector cố định — trang có cấu trúc ổn định).
3. Nếu 1 kết quả → lấy IMO/MMSI.
   Nếu NHIỀU tàu trùng tên → lọc theo voyage_no/cờ tàu bằng logic so khớp trong code
   (KHÔNG cần LLM — chỉ là so chuỗi/lọc bảng).
4. Trả Pydantic: {vessel_name, imo, mmsi, matched_voyage, confidence, source_url}.
5. Ghi vessel_registry (resolved_via = vesselfinder).
6. resolve_leg(leg_id, imo, mmsi, 'deterministic_scrape')  ← ghi shipment_legs + mirror.
```

**`resolve_leg()` — 1 hàm Python, 1 transaction (nguồn ghi duy nhất cho định danh tàu):**
```
resolve_leg(leg_id, imo, mmsi, resolved_via):
   # (1) Ghi vào NGUỒN SỰ THẬT — shipment_legs
   UPDATE shipment_legs
      SET imo=imo, mmsi=mmsi, onboarding_status='resolved', imo_resolved_via=resolved_via
    WHERE id = leg_id
   # (2) NẾU leg này đang active → mirror xuống shipments (nơi AIS worker/Agent đọc)
   IF (leg.is_active_leg == true):
      UPDATE shipments
         SET imo=imo, mmsi=mmsi, onboarding_status='resolved',
             imo_resolved_via=resolved_via, onboarding_error=NULL
       WHERE id = leg.shipment_id
   # (1) và (2) trong CÙNG 1 transaction
```
- **Chủ đích KHÔNG dùng DB trigger:** để logic mirror hiện rõ trong code Python, dễ đọc/trace/test — "không hộp đen" (cùng tinh thần với ETA rule-based và state-gate ở DB).
- Với lô `direct` (1 leg luôn active) hai bước luôn chạy cùng nhau → `shipments` và leg luôn khớp. Với `transit`, leg chưa active chỉ chạy bước (1); `shipments` vẫn phản ánh leg đang chở hàng.
- **Fallback cũng đi qua leg:** khi fail, set `shipment_legs.onboarding_status='manual_required'` + `onboarding_error`; nếu leg active thì mirror trạng thái đó lên `shipments` trong cùng transaction (để UI + retry thấy đúng).

**Chạy MỘT LẦN, không định kỳ:** định danh tàu (IMO) không đổi trong vòng đời lô → chỉ chạy lúc tạo lô (hoặc khi người dùng bấm **retry**). Khác hẳn Agent A/B (chạy định kỳ theo nhịp tracking). Điều này cũng giới hạn số lần chạm VesselFinder.

**Fallback bắt buộc (không được crash/treo):**
- Nếu VesselFinder đổi layout / chặn bot / CAPTCHA / không tìm ra / kết quả mơ hồ không phân định được → **KHÔNG crash, KHÔNG treo vô hạn**: set `shipment_legs.onboarding_status = manual_required` + `onboarding_error` (lý do); nếu leg đang active thì mirror trạng thái đó lên `shipments` (cùng transaction), báo người dùng.
- Người dùng có thể **nhập IMO/MMSI tay** cho leg (khi đó gọi `resolve_leg(leg_id, imo, mmsi, 'manual')`) hoặc bấm **retry** (chạy lại resolver cho leg đó).
- Giới hạn thời gian cho phiên browser (timeout) để tránh treo.

> **Lưu ý hạ tầng:** dù không dùng MCP, script này vẫn cần Chromium + system libs → nó chạy **trong cùng container `playwright-mcp`** (đã có sẵn Chromium), gọi qua HTTP job-queue (mục 3.7, 6.7d). KHÔNG cần cài Playwright riêng cho image Python.

#### 6.7b Carrier ETA Agent — agentic browser qua Playwright MCP

**Mục tiêu:** lấy `eta_original` (ETA baseline) tự động từ website hãng tàu bằng B/L / Booking number, thay cho việc nhập tay hoàn toàn ở v0.5.

**Cách hiện thực (agent có LLM + Playwright MCP — đây là chỗ cần LLM thật):**
- Một agent có LLM mở trang tra cứu của hãng tàu qua **tool trình duyệt của Playwright MCP** (navigate/click/snapshot/extract), điền B/L/Booking, tự đọc bảng lịch trình → trích ETA cập cảng đích. Vì mỗi hãng một giao diện, LLM quyết định thao tác theo trang thực tế.
- **Giới hạn 2-3 hãng tàu cho demo** — khoanh vùng để kiểm soát độ ổn định khi demo.
- Kết quả ghi vào `eta_original` (+ `eta_original_source = carrier_scrape`) + một dòng `eta_history` (source = `original`).

**Fallback:** nếu không tra được (layout đổi, cần đăng nhập, CAPTCHA) → **nhập tay `eta_original`** (`eta_original_source = manual`) từ Booking Confirmation/B/L (đúng như v0.5). Carrier ETA lookup là **tiện ích tự động hóa thêm**, không phải điểm chặn — thiếu nó vẫn onboarding được bằng tay.

> **Giá trị cốt lõi vẫn là ETA ĐỘNG (mục 6.3), không phải con số baseline này.** Dù baseline lấy tự động hay nhập tay, điểm ăn tiền của hệ thống là cập nhật ETA động từ AIS + thời tiết. Nêu rõ để không bị hiểu nhầm demo "chỉ đi scrape ETA của hãng".

#### 6.7c Ranh giới an toàn (nhất quán với Email/Research Agent)

- Cả (a) và (b) chỉ ghi định danh tàu + ETA baseline — đây là dữ liệu onboarding, **không phải** `eta_current`. Không đụng tới vòng cảnh báo ETA động.
- Trang web ngoài là **nguồn không tin cậy** (giống email ở mục 7.2): chỉ **đọc** (tra cứu), không thực hiện thao tác ghi/đăng nhập bằng credential thật của U&I trong demo. Nếu một hãng bắt buộc đăng nhập → coi như ngoài phạm vi, rơi về nhập tay.
- Kết quả phân giải có `confidence` + `source_url` để người dùng đối chiếu khi cần (đặc biệt case trùng tên tàu).

#### 6.7d Worker Pool + Job Queue cho onboarding (Redis + BullMQ, qua HTTP boundary)

**Vấn đề cần giải:** ở quy mô lớn (bulk import), nhiều yêu cầu onboarding có thể tới gần **cùng lúc**, trong khi mỗi phiên scrape phải launch/giữ một **browser context** (nặng RAM) — không thể chạy song song không giới hạn (dễ OOM trên VPS). Cần: (1) giới hạn số phiên browser đồng thời, (2) hàng đợi cho job vượt giới hạn, (3) retry/timeout có sẵn — **không tự viết lại logic queue**.

**Ranh giới ngôn ngữ — Python KHÔNG chạm Redis/BullMQ trực tiếp:** BullMQ là thư viện Node; backend là Python/FastAPI. Thay vì dùng bản port `bullmq-python` (non trẻ) hay chia sẻ format Redis nội bộ, giải bằng **HTTP boundary** (giao thức chuẩn, ổn định):

```
┌─────────────────────────────────────────────────────────────┐
│ Backend Python (container webapp)                            │
│  - Onboarding trigger: check vessel_registry (cache hit?)    │
│  - Miss → HTTP POST /scrape-jobs (payload: vessel_name,      │
│    voyage_no, bl_number, carrier...)                         │
│  - Poll GET /scrape-jobs/:id  (hoặc webhook callback)        │
│  → KHÔNG bao giờ chạm Redis                                  │
└───────────────────────────┬─────────────────────────────────┘
                            │ HTTP (REST)
┌───────────────────────────▼─────────────────────────────────┐
│ container playwright-mcp (Node) — HAI cửa vào:               │
│  1) REST nhỏ (Express/Fastify): /scrape-jobs (IMO Resolver   │
│     deterministic — fire-and-forget + poll)                  │
│  2) MCP network transport: tool trình duyệt cho Carrier ETA  │
│     Agent (agentic, LLM ở Python điều khiển từng bước)       │
│  ┌────────────────────────────────────────────────────────┐ │
│  │ BullMQ Worker (concurrency = 2-3, config 1 dòng)         │ │
│  │  - playwright-mcp quản lý các phiên Chromium trong cùng container │ │
│  │  - BullMQ giới hạn browser context đồng thời; mỗi job có context riêng │ │
│  │  - retry/timeout do BullMQ lo sẵn                        │ │
│  │  → trả kết quả JSON về Python qua polling (Node KHÔNG chạm Postgres) │ │
│  └────────────────────────────────────────────────────────┘ │
└───────────────────────────┬─────────────────────────────────┘
                            │ BullMQ client (nội bộ Node)
                    ┌────────▼────────┐
                    │ container redis  │  (redis:alpine, ~30-50MB idle)
                    │ job queue (BullMQ)│
                    └──────────────────┘
```

- **Hai cửa vào cùng một container**, chung trần concurrency: **MVP dùng Chromium do container `playwright-mcp` quản lý — BullMQ concurrency giới hạn số browser context đồng thời** (KHÔNG khẳng định hai process dùng chung một tiến trình Chromium duy nhất). (1) IMO Resolver deterministic hợp mô hình "gửi job → poll" nên đi qua REST `/scrape-jobs`; (2) Carrier ETA agentic là LLM ở Python click từng bước qua MCP nên đi qua MCP transport riêng — KHÔNG qua `/scrape-jobs`. Cả hai Python **không chạm Redis**. Hướng chuyển browser thành service tập trung (Browserless) là scale-ahead ở mục 6.7e — KHÔNG phải runtime dependency của MVP.
- **Nhất quán với "không Kafka" (điểm phòng thủ quan trọng):** Kafka bị loại vì giải bài toán **throughput** (không có ở quy mô này). Job queue ở đây giải bài toán **khác bản chất** — tài nguyên đắt (browser context) không chạy song song vô hạn được. *Thành thật khi bảo vệ:* ở đúng quy mô 3-5 lô, một `asyncio.Semaphore(2-3)` cap số context là đã đủ; **MVP bắt buộc Redis + BullMQ; semaphore-only chỉ là phương án scale-ahead/đơn giản hóa ngoài MVP.** Nếu hội đồng hỏi "sao 3-5 lô cần Redis?", trả lời thẳng: cap concurrency mức MVP không cần Redis, nhưng thiết kế job-queue để chứng minh đường mở rộng khi import hàng loạt — và tách nhẹ, chỉ +1 container `redis:alpine`.
- **MVP bắt buộc Redis + BullMQ; semaphore-only chỉ là phương án scale-ahead/đơn giản hóa ngoài MVP.**

#### 6.7e Browserless — centralized browser service **[STRETCH / SCALE-AHEAD, KHÔNG cam kết build trong demo]**

> **[v0.9.15]** Mục này là **thiết kế-trước hướng scale**, KHÔNG phải runtime dependency của MVP. Kiến trúc hiện tại (container `playwright-mcp`: Express + BullMQ + Redis + Chromium + `@playwright/mcp`, mục 6.7d) **giữ nguyên làm implementation chính của demo** — không đập TASK-10/11/12.

**Vấn đề khi scale:** ở MVP mỗi container `playwright-mcp` tự quản Chromium riêng (BullMQ cap số browser context đồng thời trong container đó). Khi số worker/máy tăng (nhiều instance business worker, bulk import lớn), mỗi instance ôm 1 Chromium làm tài nguyên browser rải rác, khó cap tổng số session toàn hệ + business worker phải stateful hơn (giữ vòng đời browser).

**Hướng scale-ahead:** chuyển browser thành **resource pool tập trung** — [Browserless](https://www.browserless.io/) (hoặc dịch vụ tương đương) chạy như 1 service riêng, expose **remote CDP WebSocket**; các worker kết nối qua CDP thay vì tự launch Chromium. Browserless có **concurrency/queue built-in** (cap tổng số session, xếp hàng job vượt trần ở tầng service) → business worker **stateless hơn** (chỉ mở remote session, không giữ Chromium local). Tương lai đổi backend browser (local → Browserless) **không phải sửa agent/domain** vì đã có gateway `BrowserAgentClient` (TASK-12) làm ranh giới: nhận task, trả structured result, có timeout/error mapping — Carrier ETA Agent KHÔNG phụ thuộc trực tiếp browser chạy local hay Browserless. (Đợt này CHƯA viết Browserless adapter thật.)

**Điều kiện kích hoạt (TASK-18+, SAU khi):** (1) spike remote-CDP pass — **cần verify: bản `@playwright/mcp` đã pin (mục 3.6/IC) CÓ hỗ trợ trỏ tới Browserless remote CDP hay không (CHƯA xác nhận)**; `spike_mcp.py` (TASK-01) nên kiểm thêm khả năng kết nối remote-CDP/Browserless như *compatibility evidence* — nhưng đây KHÔNG phải điều kiện để đổi kiến trúc MVP, kết quả chỉ để ghi nhận, không block build; (2) benchmark 3-5 session đồng thời đạt yêu cầu.

**Known Limitations (mục 14):** Browserless queue/concurrency cần benchmark thực tế + kiểm license/operational (self-host vs SaaS, chi phí) TRƯỚC production. Ghi rõ để không nhầm "đã có gateway" = "đã scale được".

### 6.8 Transit (chuyển tải) + Rollover (đổi tàu giữa đường) — **[STRETCH / thiết kế-trước]**

> **[STRETCH — KHÔNG cam kết build trong demo]** Cả 2 tuyến demo (nhập và xuất C/D, mục 1.4) đi **thẳng một chặng**, không chạm transit. Toàn bộ mục 6.8 là **thiết kế-trước** để kiến trúc không kẹt khi sau này gặp lô nhiều chặng — KHÔNG nằm trong phạm vi build cam kết cứng. Ghi vào bài luận như phần "mở rộng đã tính trước", không phải tính năng đã chạy.

**Vấn đề vá:** v0.8 ngầm giả định **1 lô = 1 tàu cố định** suốt hành trình. Thực tế vỡ theo 2 cách:
- **(a) Transit thật** — tuyến nhiều chặng qua **cảng chuyển tải** (VD Hải Phòng → Singapore chuyển tải → Rotterdam). Biết trước từ lịch trình hãng tàu.
- **(b) Rollover** — hãng **đổi tàu giữa chừng** (tàu đầy chỗ, đổi lịch), **KHÔNG báo trước**, thường qua email "Rollover Notification / Vessel Change Notice".

Cả hai cần **cùng một cơ chế nền:** theo dõi **nhiều bản ghi tàu theo thời gian** cho một lô (bảng `shipment_legs`, mục 4.8), biết bản ghi nào đang **active** để AIS subscribe đúng con tàu đang chở hàng.

**Nguyên tắc xuyên suốt — TÁI DÙNG hạ tầng, KHÔNG thêm agent (nhất quán "đúng độ phức tạp cho đúng việc"):**

| Việc mới của transit | Dùng lại thành phần nào | KHÔNG làm gì |
|---|---|---|
| Phát hiện lô có chuyển tải | **Carrier ETA Agent (6.7b)** — mở rộng Pydantic output để trích danh sách chặng | Không thêm agent phát hiện transit riêng |
| Tra IMO/MMSI tàu chặng sau | **IMO Resolver (6.7a)** deterministic — y hệt chặng đầu | Không viết logic tra tàu mới |
| Lịch quét định kỳ tàu chặng sau | **BullMQ repeatable job** (hạ tầng 6.7d đã có) | Không bảng cronjob mới, không scheduler mới |
| Điều phối thứ tự | **State gate ở DB** (`shipment_legs.onboarding_status` + `is_active_leg`) | Không handoff hội thoại AG2 |

> **Vì sao KHÔNG thêm "Agent 3":** việc của transit không có suy luận/hội thoại nhiều lượt mới — chỉ là "đọc 1 trang lịch trình → trả structured output" ở **tần suất khác** (định kỳ thay vì 1 lần). Đây đúng là việc Carrier ETA Agent đã làm; chỉ khác là chạy lại theo lịch. AG2 vẫn dành riêng cho điều phối hội thoại thật (A↔B). Thêm agent ở đây là over-engineering — cùng lý lẽ với "không Kafka".

#### 6.8a Phát hiện transit — mở rộng Carrier ETA Agent

- Khi Carrier ETA Agent (6.7b) đọc lịch trình hãng tàu, **mở rộng Pydantic output** để trích thêm **danh sách chặng** (các cảng trung gian, nhãn "Transshipment"/"Via" trên trang lịch trình).
- **Quy tắc phân loại:**
  - Chỉ 2 điểm (POL → POD), không cảng trung gian → `shipments.shipment_type = direct`. Tạo đúng 1 leg (`leg_no=1`).
  - Có cảng trung gian → `shipments.shipment_type = transit`. Tạo nhiều leg trong `shipment_legs` (mỗi chặng 1 dòng, `pol/pod` riêng chặng).
- Việc phân loại này chỉ là **đọc output có sẵn của agent** — không thêm bước LLM riêng.

#### 6.8b Tra IMO các chặng — dùng lại IMO Resolver + BullMQ repeatable job

- Mỗi leg cần IMO/MMSI riêng → gọi **IMO Resolver (6.7a)** cho từng leg (qua `leg_id`), ghi kết quả bằng `resolve_leg()`.
- **Lịch quét:**
  - **Direct:** một lần (như hiện tại) — leg 1 resolve xong là xong onboarding.
  - **Transit:** sau lần scrape đầu, đăng ký **BullMQ repeatable job** gọi **cùng** Carrier ETA Agent định kỳ (lịch trình chặng sau có thể chưa công bố lúc tạo lô, hoặc thay đổi) → khi chặng kế có tàu/lịch thì tra IMO chặng đó. **`removeRepeatable`** khi lô đã giao (`delivered`) hoặc chặng cuối đã resolved.
  - **Tần suất:** tạm để **6h hoặc 12h** — **[chưa chốt, chưa có dữ liệu thật để hiệu chỉnh]**. Không cần thường xuyên vì lịch trình chặng sau đổi chậm.
- Không có bảng cronjob mới: BullMQ repeatable job là tính năng sẵn có của hạ tầng job-queue (6.7d).

#### 6.8c Chuyển leg active — **TÍN HIỆU KÉP** (agent = danh tính, AIS = thời điểm)

Điểm tinh tế nhất. Khi nào chuyển `is_active_leg` từ chặng cũ sang chặng mới? Hai nguồn tín hiệu **tách vai rõ ràng:**

| Nguồn | Trả lời câu hỏi | Ghi gì |
|---|---|---|
| **Carrier ETA Agent** (định kỳ, 6.8b) | Tàu chặng sau **là con nào** (danh tính: vessel_name → IMO/MMSI) | Ghi vào `shipment_legs` chặng sau — **nhưng CHƯA set active** |
| **AIS** (realtime, tàu hiện tại) | **Khi nào** đã sang chặng mới (thời điểm) | Không ghi danh tính — chỉ báo hiệu tàu cũ đã rời cảng chuyển tải |

**Logic chuyển (code deterministic, KHÔNG LLM, KHÔNG AG2):**
```
Điều kiện chuyển leg (kiểm định kỳ trong AIS worker hoặc job riêng):
  1. Tàu hiện tại (leg đang active) tới gần toạ độ CẢNG CHUYỂN TẢI (so haversine với
     toạ độ cảng chuyển tải của leg — nằm trong bán kính X km)
  2. VÀ tốc độ (SOG) ~0 một thời gian (đã cập cảng), RỒI tăng lại > ngưỡng
     (dấu hiệu con tàu CŨ rời cảng — hàng đã dỡ sang tàu sau)
  3. VÀ leg kế tiếp đã có IMO/MMSI (Carrier ETA Agent đã điền danh tính)
  → LÚC ĐÓ mới: switch_active_leg(shipment_id, next_leg_id)
```

**`switch_active_leg()` — cùng quy tắc 1-transaction như `resolve_leg()`:**
```
switch_active_leg(shipment_id, next_leg_id):
   # tất cả trong CÙNG 1 transaction
   UPDATE shipment_legs SET is_active_leg=false WHERE shipment_id=... AND is_active_leg=true
   UPDATE shipment_legs SET is_active_leg=true  WHERE id=next_leg_id
   # mirror toàn bộ danh tính leg mới xuống shipments (nơi AIS worker đọc)
   UPDATE shipments
      SET imo=<next.imo>, mmsi=<next.mmsi>, onboarding_status=<next.onboarding_status>,
          imo_resolved_via=<next.imo_resolved_via>, onboarding_error=<next.onboarding_error>
    WHERE id = shipment_id
   → bắn asyncio.Event → AIS worker resubscribe sang tàu chặng mới NGAY (mục 3.1),
     không chờ chu kỳ poll 60s
```
- **Vì sao tách vai:** agent scrape **không biết thời điểm thực tế** tàu sang chặng (lịch trình chỉ là dự kiến); AIS **không biết danh tính tàu sau** (chỉ thấy tàu hiện tại). Ghép hai nguồn: agent lo *là tàu nào*, AIS lo *khi nào* — tránh chuyển sớm (subscribe nhầm tàu chưa khởi hành) hoặc chuyển hụt.
- **Quyết định chuyển là code deterministic** (so toạ độ + đọc DB) — đúng nguyên tắc "state gate ở DB, không AG2 handoff" (mục 6.7).

#### 6.8d Rollover — cùng cơ chế, khác trigger (qua Email Agent, mục 7.1)

Rollover là "đổi tàu **trong cùng một chặng**", trigger từ **email** thay vì lịch trình:
- Email Agent (7.1) nhận "Rollover Notification" có **tên tàu mới** → người dùng duyệt.
- Khi duyệt: ngoài cập nhật `eta_current`, hệ thống gọi **`resolve_and_activate_leg()`** — tra lại IMO/MMSI tàu mới (gọi IMO Resolver 6.7a) → ghi **dòng mới** vào `shipment_legs` với **CÙNG `leg_no`** (không phải chặng kế tiếp — vẫn là chặng đó, chỉ đổi tàu), đánh dấu dòng cũ `superseded_at = now()`, **rồi chuyển `is_active_leg=true` NGAY LẬP TỨC trong cùng transaction**.
- **Rollover KHÔNG đi qua điều kiện tín hiệu kép của 6.8c** (toạ độ cảng chuyển tải + tốc độ AIS). Vì sao khác transit: điều kiện 6.8c tồn tại để bù cho việc **agent-scrape lịch trình không đủ tin cậy về *thời điểm*** tàu sang chặng ở một transit thật (có cảng chuyển tải xác định để so toạ độ). Rollover thì (a) đã có **người duyệt** làm lớp tin cậy thay thế, và (b) nhiều case hãng đổi tàu **trước khi khởi hành**, không xảy ra tại một cảng chuyển tải xác định → không có toạ độ để so. Ép rollover qua gate 6.8c sẽ khiến việc chuyển active **treo vô thời hạn**.
- Vì vậy tách rõ **hai hàm** để không nhầm nhánh: **`switch_active_leg()`** (mục 6.8c) chỉ dùng cho **transit** — chuyển active khi gate 2 tín hiệu thỏa; **`resolve_and_activate_leg()`** dùng cho **rollover** — tra IMO + chuyển active ngay sau khi người duyệt, không gate AIS.
- Cả hai đều mirror MMSI mới xuống `shipments` (cùng transaction) và **bắn `asyncio.Event`** để AIS worker resubscribe ngay (mục 3.1), không chờ chu kỳ poll.
- Giữ dòng cũ (không xóa) để **trace lịch sử đổi tàu** — bằng chứng "hệ thống bắt được rollover" cho bài luận.

```
resolve_and_activate_leg(new_leg_id, imo, mmsi, resolved_via):
   # tất cả trong CÙNG 1 transaction
   # (1) ghi danh tính tàu mới vào leg mới (nguồn sự thật)
   UPDATE shipment_legs SET imo=imo, mmsi=mmsi,
          onboarding_status='resolved', imo_resolved_via=resolved_via WHERE id = new_leg_id
   # (2) hạ leg cũ, nâng leg mới thành active (rollover đã có người duyệt → chuyển ngay)
   UPDATE shipment_legs SET is_active_leg=false WHERE shipment_id=<sid> AND is_active_leg=true
   UPDATE shipment_legs SET is_active_leg=true  WHERE id = new_leg_id
   # (3) mirror danh tính mới xuống shipments (nơi AIS worker đọc)
   UPDATE shipments SET imo=imo, mmsi=mmsi, onboarding_status='resolved',
          imo_resolved_via=resolved_via, onboarding_error=NULL WHERE id = <sid>
   → bắn asyncio.Event → AIS worker resubscribe sang tàu mới NGAY (mục 3.1)
```

#### 6.8e Ranh giới an toàn (nhất quán 6.7c / 7.2)

- Carrier ETA Agent định kỳ vẫn chỉ **đọc** lịch trình, ghi `shipment_legs` (danh tính) + `eta_original`-mức-chặng — **không đụng `eta_current`** (vòng cảnh báo ETA động vẫn do rule-based, mục 6.3).
- Chuyển leg + rollover-update là **code deterministic** hoặc **có người duyệt** (rollover qua Email Agent) — không có đường nào để agent/LLM tự đổi tàu active mà không qua state-gate hoặc người duyệt.

---

## 7. Module 2 — Agent email (human-in-the-loop)

### 7.1 Luồng hoạt động
```
Email hãng tàu vào mailbox delegate
   → Agent ĐỌC & trích xuất cho MỌI mail hợp lệ vào hộp (bất kể monitoring_mode) — xem [v0.9.7] bên dưới:
       [v0.9.9 — viết lại theo monitoring_mode, bỏ nhóm chữ cái] monitoring_mode CHỈ gate luồng FORWARD:
       lô `auto_email` (nhập E/F hoặc xuất C/D — suy từ cặp direction × Incoterm, bảng §5) = auto-forward
       tới whitelist nội bộ; lô `manual` (nhập C/D) = forward tay do người dùng tự quyết.
       monitoring_mode KHÔNG gate việc Agent đọc/đề xuất: mail của lô `manual` (forward tay vào hộp)
       vẫn được Agent trích xuất + tạo proposal như lô `auto_email` — user vẫn hưởng lợi từ trích xuất
       LLM; hai mode chỉ khác nhau ở bước forward.
   → LLM trích xuất: {containers[], from_voyage, to_voyage, new_eta, reason}  (mail có thể nhắc NHIỀU container)
   → Map từng container vào shipment tương ứng:
       - container khớp shipments.container_no → tạo 1 dòng agent_proposals riêng cho container đó
       - container lạ (không có trong hệ thống) → [v0.9.6] bỏ qua, chỉ ghi log (mail nguồn, container,
         thời điểm) để trace — KHÔNG tạo agent_proposals, KHÔNG chặn các container khớp còn lại trong mail
   → Ghi agent_proposals (status = pending) cho (các) container khớp — KHÔNG sửa shipments
   → Hiện cho user: "Nhận mail rớt tàu cont X, dời từ chuyến A sang B, ETA mới Y. Cập nhật?"
   → User duyệt / từ chối (đối chiếu với email gốc)
   → Nếu duyệt: cập nhật shipments.eta_current + ghi eta_history (source = email_agent)
      + NẾU là rollover có TÊN TÀU MỚI (mục 6.8d): gọi resolve_and_activate_leg()
        → tra lại IMO/MMSI tàu mới (IMO Resolver 6.7a)
        → ghi dòng mới vào shipment_legs CÙNG leg_no, superseded_at dòng cũ
        → chuyển is_active_leg NGAY (rollover đã có người duyệt, KHÔNG qua gate 6.8c)
        → mirror MMSI mới xuống shipments + bắn asyncio.Event → AIS resubscribe ngay
```

> **Rollover kéo theo tra lại IMO (v0.9, mục 6.8d):** thông báo rollover không chỉ đổi ETA — nó đổi **con tàu**. Vì AIS subscribe theo MMSI, đổi tàu mà không tra lại IMO/MMSI thì AIS vẫn bám tàu cũ (đã rời đi không chở lô này). Nên khi user duyệt một rollover có tên tàu mới, hệ thống phải chạy IMO Resolver cho tàu mới và ghi vào `shipment_legs` (cùng `leg_no`, dòng cũ `superseded_at`) — xem chi tiết mục 6.8d. Với lô không có `shipment_legs` transit (direct), đây vẫn là 1 leg, chỉ thay tàu trong leg đó.

### 7.2 Nguyên tắc an toàn (bắt buộc)
- Agent ở **chế độ ĐỀ XUẤT**, tuyệt đối không tự sửa dữ liệu lô hàng, không tự gửi mail. Quyết định luôn là của người.
- Lý do không chỉ là UX mà là **bảo mật**: email đến từ bên ngoài là **nguồn KHÔNG tin cậy** (untrusted). Một email mơ hồ, sai định dạng, giả mạo, hoặc chứa chỉ thị lồng vào để thao túng agent (prompt injection) có thể khiến LLM trích sai. Human-in-the-loop là **rào chắn an ninh bắt buộc**.
- Dùng **hộp thư delegate riêng** cho agent, tách hẳn khỏi inbox chính — giới hạn phạm vi truy cập. Không đụng dữ liệu khách hàng thật.

### 7.3 Dữ liệu test
Tự soạn vài email mẫu mô phỏng thông báo hãng tàu (dựa trên **format email thật xin được từ U&I** — tài liệu quý cho cả demo lẫn phụ lục bài luận): rollover notification, vessel change notice, transit delay. Gửi vào mailbox delegate để agent xử lý → demo luôn tái lập được.

### 7.4 Cách đọc mailbox + forward theo `monitoring_mode` **[v0.9.9 đổi tên: trước là "theo Incoterm" — mode mới là trục quyết định, không phải nhóm chữ cái]**

**Đọc mailbox:**
- Gmail API (OAuth) hoặc IMAP. Với demo, IMAP đơn giản hơn để bắt đầu; Gmail API sạch hơn nếu muốn.
- **[Lưu ý]** OAuth/cấp quyền truy cập mailbox là bước cần chính bạn thực hiện (đăng nhập tài khoản của bạn) — phần xác thực không làm hộ được.
- **[khi lên production]** Để mailbox delegate nhận thông báo thật từ hãng tàu, cần: thiết lập rule tự động forward từ inbox thật của user U&I sang mailbox delegate của hệ thống .

**Cơ chế dọn mail sau xử lý [v0.9.10-p2 — bổ sung, từng thiếu]:** email agent poll IMAP theo nhịp `EMAIL_POLL_INTERVAL_MINUTES`, chỉ fetch `UNSEEN` mail. Sau khi xử lý xong 1 mail (bất kể outcome: `proposals_created` / `no_match` / `rejected_allowlist` / `parse_failed`), agent `STORE <uid> +FLAGS \Seen` trên IMAP server → mail vẫn nằm trong inbox nhưng đã đánh dấu đã đọc → poll kế không fetch lại. Kết hợp với `processed_emails.message_id` dedup (mục 0.2 IC) tạo 2 lớp phòng vệ: `\Seen` giảm fetch overhead, `processed_emails` chống trùng xử lý nếu `\Seen` bị reset (VD Gmail web UI đọc tay mail đó — nhưng mailbox delegate DÀNH RIÊNG, không ai đọc web UI, nên nhược đồng bộ `\Seen` với web UI không xảy ra — đúng nguyên tắc §7.2 giới hạn phạm vi).

**Chọn `\Seen` + giữ mail trong inbox thay vì `\Deleted` + expunge** vì 3 lý do: (1) audit trail 3 lớp (mail gốc trong inbox + `processed_emails` row + `agent_proposals.source_email_id` → truy vết đầy đủ, đúng mục tiêu §3.8); (2) nếu agent trích sai cần đọc lại mail gốc, mail còn trong inbox không phải vào Thùng rác tìm; (3) Gmail map `\Deleted` khác Outlook — `+FLAGS \Deleted` có thể không đưa mail vào Thùng rác ngay mà chỉ ẩn khỏi inbox khi expunge, cần test với mailbox delegate thật trước khi dùng. Nếu sau này muốn inbox sạch (VD mailbox cũng là Gmail cá nhân không tách hẳn), thêm job dọn inbox định kỳ — ghi vào future work, không gấp với demo 3-5 lô.

**IMAP client + UID:** dùng `aioimaplib` (native async — khuyến nghị cho FastAPI) hoặc `imap-tools` bọc qua `asyncio.run_in_executor` (imap-tools là sync library, không native async). Fetch bằng UID (ổn định hơn sequence number — sequence đổi khi mail expunge, UID không đổi trong lifecycle mail). `STORE` cũng theo UID. Nếu IMAP server không trả UID → fallback fetch bằng Message-ID header (khớp `processed_emails.message_id`).

**Giữ thiết kế một hòm mail hệ thống (v0.9):** vẫn dùng **một mailbox delegate chung** cho toàn hệ thống (không tách hòm thư theo từng user).

**Allowlist KÉP (v0.9.6 — sửa lỗi thiết kế; v0.9.8 — mở rộng (A) sang mọi lô `auto_email`):** một allowlist domain hãng tàu duy nhất, lọc theo From ngoài cùng, **đá nhau** với chính cơ chế forward tay mà mục này mô tả cho nhập C/D — sau khi forward (kể cả "true forwarding" khuyến nghị bên dưới), From ngoài cùng là địa chỉ người forward (nhân viên U&I), không còn là domain hãng tàu → allowlist domain sẽ loại bỏ đúng mail hợp lệ. Tách thành **hai allowlist độc lập**, cả hai vẫn lọc trên **From ngoài cùng** của mail tới hộp delegate (không cần agent parse lớp lồng bên trong trước khi quyết định có xử lý mail hay không):

- **(A) Allowlist domain hãng tàu** (VD `@maersk.com`, `@msc.com`, `@one-line.com`...) — áp cho **mọi lô `monitoring_mode = auto_email`** (**[v0.9.8]** nhập E/F **VÀ xuất C/D** — cả hai đều nhận mail trực tiếp từ hãng tàu, không qua trung gian), nơi From ngoài cùng vẫn giữ nguyên domain hãng tàu.
- **(B) Allowlist địa chỉ người forward nội bộ** — danh sách email nhân viên U&I được cấu hình trước, những người được phép manual-forward mail transit/rollover vào mailbox delegate — áp cho **lô `monitoring_mode = manual`** (**[v0.9.8]** nay chỉ còn nhập C/D — nhánh `manual` duy nhất sau khi thêm xuất C/D vào `auto_email`).

Mail đến từ địa chỉ không nằm trong (A) hoặc (B) thì bỏ qua như cũ (giảm nhiễu + hạ rủi ro xử lý mail giả mạo). Vai trò của allowlist chỉ là giảm nhiễu ở bước nhận mail — KHÔNG phải xác thực nội dung bên trong là thật của hãng tàu; xác thực nội dung vẫn do người duyệt đảm nhiệm như từ trước tới giờ (nguyên tắc human-in-the-loop, mục 7.2).

**[Ghi chú kỹ thuật quan trọng — định dạng email sau auto-forward, v0.9]:** khi U&I forward mail hãng tàu vào mailbox delegate, **cách forward ảnh hưởng độ chính xác trích xuất của LLM (7.1):**
- **Outlook "Forward as attachment" / Outlook Rules dạng attachment:** bọc email gốc thành phần **quoted/nested** bên trong mail forward → header người gửi gốc, tiêu đề, nội dung nằm **lồng** trong lớp forward. LLM trích xuất (7.1) phải **parse xuyên qua lớp quoted/forwarded content** mới lấy đúng dữ liệu gốc → dễ sai hơn.
- **Gmail "true forwarding":** giữ định dạng gốc khá tốt, ít bọc lớp → LLM trích xuất chính xác hơn.
- **Khuyến nghị: hướng dẫn user ưu tiên "true forwarding"** thay vì forward-as-attachment (ghi vào giới hạn mục 9).
- **Về trace:** `agent_proposals.source_email_id` (mục 4.4) chỉ trace về **message-id của email đã forward** (không phải email gốc của hãng) → đây là **trace gián tiếp**; khi cần đối chiếu tuyệt đối phải mở email forward ra xem lớp gốc bên trong.

**Forward email theo `monitoring_mode` — auto vs manual ([v0.9.8] viết lại theo mode, không còn theo nhóm chữ cái E/F/C/D trần):** bảng trước map thẳng "nhóm E/F → auto-forward, nhóm C/D → manual-forward" — điều này giờ **sai** vì xuất C/D cũng thuộc `auto_email`. Map lại đúng theo `monitoring_mode` đã suy ra ở mục 5 (dựa trên cặp `direction × Incoterm`, không phải nhóm chữ cái đơn thuần):

| `monitoring_mode` | Case | Đặc điểm nội dung mail | Chiến lược forward |
|---|---|---|---|
| `auto_email` | Nhập E/F, **Xuất C/D [v0.9.8 MỚI]** | Nhận trực tiếp từ hãng tàu — format chuẩn hóa, cấu trúc ổn định (Rollover Notification, Vessel Change Notice) | **Auto-forward** — nội dung đủ tin để chuyển tiếp theo template |
| `manual` | Nhập C/D | Qua đại lý/bên bán, không chuẩn hóa, dễ nhiễu, thể thức tự do | **Manual-forward** — người dùng đọc và tự quyết chuyển tiếp |

> **Rào an toàn cho auto-forward (BẮT BUỘC):** auto-forward CHỈ được gửi tới **danh sách người nhận nội bộ đã cấu hình trước** (whitelist), **KHÔNG lấy địa chỉ nhận từ nội dung email đến**. Lý do: email đến là nguồn không tin cậy (đúng nguyên tắc mục 7.2) — nếu auto-forward dựa trên địa chỉ trong nội dung email, nó có thể bị lợi dụng để phát tán thông tin ra địa chỉ lạ (kênh rò rỉ dữ liệu). Kèm theo: mọi lần auto-forward đều **ghi log để trace**. Đây là điểm bảo mật quan trọng, không được bỏ.

---

## 8. Các bước triển khai (thứ tự build đề xuất)

Xây từ nền lên, phân 3 tầng ưu tiên để nếu trễ tiến độ thì phần lõi vẫn chạy độc lập và demo vẫn có giá trị.

**■ LÕI CAM KẾT CỨNG (bước 1-6) — phải chạy chắc chắn:**
1. **Test kết nối dữ liệu (spike)** — script nhỏ nghe aisstream.io (WebSocket) + gọi Open-Meteo, in ra dữ liệu thật (MMSI, lat/lon, SOG, COG). Bước gỡ rủi ro lớn nhất, làm trước khi thiết kế ETA engine.
2. **DB + model** — dựng PostgreSQL, tạo **10 bảng thực thi**: 8 bảng nghiệp vụ ở §4 + 2 bảng bổ sung chuẩn tắc `env_conditions` và `processed_emails` (IC§0.2). Có đầy đủ `vessel_registry`, `users`, `shipment_legs`, các cột onboarding/direction/audit; seed 4 lô + 2 user theo IC§13, gồm ít nhất 1 lô export C/D. Schema không phụ thuộc OAuth runtime.
3. **Backend CRUD lô hàng** — REST nhập/sửa/xem lô. **[v0.9.9 — sửa theo logic 2 chiều v0.9.8:** nhập cặp `(shipment_direction, incoterm)` → suy ra `monitoring_mode` theo bảng §5 (KHÔNG suy 1 chiều từ Incoterm đơn); UI chọn direction trước, dropdown Incoterm lọc theo direction — **ẩn nhóm E/F khi `export`**]; nhập tay IMO/MMSI + `eta_original` như đường fallback.
4. **AIS worker** — async task giữ WebSocket, upsert vị trí realtime vào `shipments`, tự reconnect. **CHỈ subscribe lô `onboarding_status = resolved`.** Song song: job snapshot `vessel_trail` mỗi 6h (rolling 12 điểm/lô).
5. **ETA engine** — Tầng 1 (6.3) + Tầng 2 điều chỉnh thời tiết/dòng chảy (6.3), ghi `eta_history`, sinh cảnh báo. **Phần bắt buộc phải chạy chắc chắn.**
6. **Frontend cơ bản + WebSocket** — danh sách lô + chi tiết (progress bar milestone + Leaflet map + vệt trail + ETA động đổi màu). Backend đẩy update realtime.

**■ NÂNG CHẤT (bước 7-13):**
7. **Weather/Wave/Current + Tide poll hoàn chỉnh** — **[v0.9.9]** Open-Meteo định kỳ (wind + wave + current trong **1 lệnh gọi**, mục 6.2/6.3) + **Stormglass tide** cron 12h cho lô đang trên biển (mục 6.6; geocode cảng đích qua World Port Index tải offline 1 lần).
8. **Agent A — ETA Reasoning Agent (Layer 3, AG2)** — cấu hình agent AG2, đăng ký tool bước 4-7, sinh "nhận định chuyên gia" (6.3b), KHÔNG ghi đè ETA baseline. Pin version AG2. **Chỉ chạy cho lô `resolved`.**
9. **Agent B — Research Agent (Core, AG2) + cache** — agent AG2 riêng có tool web search, vòng A↔B với Agent A, Pydantic validate, ghi `research_findings` (6.3c) + cache theo tuyến (6.3d). Test Agent B độc lập trước khi nối vòng lặp với Agent A.
10. **Container playwright-mcp + hàng đợi (mục 3.7, 6.7d)** — dựng container Node (`@playwright/mcp` + REST endpoint `/scrape-jobs` chạy BullMQ nội bộ, concurrency 2-3, Chromium do container quản lý với mỗi job một browser context riêng) + container `redis:alpine`. Build cross-arch bằng `docker buildx build --platform linux/amd64` hoặc dùng image `mcr.microsoft.com/playwright` (đã có sẵn Chromium + system libs). MCP transport để HTTP/SSE (network, không stdio) vì tách container riêng. **MVP bắt buộc Redis + BullMQ; semaphore-only chỉ là phương án ngoài MVP/scale-ahead, không được dùng thay thế trong demo.**
11. **IMO Resolver — script Playwright viết cứng, KHÔNG LLM (mục 6.7a)** — backend Python gọi `POST /scrape-jobs` → worker Node chạy script deterministic tra VesselFinder (selector cố định, lọc trùng tên bằng voyage trong code) → trả IMO/MMSI qua polling `GET /scrape-jobs/:id` → ghi `vessel_registry` + `imo_resolved_via`, set `onboarding_status`. Fallback `manual_required` + `onboarding_error` + nút retry. Test riêng con tàu trùng tên.
12. **Carrier ETA Agent — agentic qua Playwright MCP (mục 6.7b)** — agent có LLM gọi tool trình duyệt qua MCP transport (HTTP/SSE) cho 2-3 hãng khác layout, điền `eta_original` + `eta_original_source = carrier_scrape`. Fallback nhập tay.
13. **Agent email (Module 2)** — mailbox delegate riêng, LLM trích xuất, `agent_proposals` + hộp duyệt trên frontend (mục 7).

**■ VẬN HÀNH / BẢO MẬT (bước 14-15) — bắt buộc trước khi công khai:**
14. **Auth — OAuth Google + Microsoft (mục 3.8)** — tích hợp **Authlib** (OIDC), endpoint `/auth/login/{provider}` + `/auth/callback/{provider}` (test hardcode port **1476**), đổi `code` lấy `id_token` → tạo/cập nhật `users`, tự phát hành **session JWT riêng** (không dùng thẳng token provider), middleware verify bảo vệ route. Đăng ký mở cho mọi tài khoản (role mặc định `user`). Nối `decided_by`/`verified_by` vào hành động duyệt/xác minh. **PHẢI xong trước bước 15** — deploy công khai mà chưa có auth là mở toang DB + phá audit trail.
15. **Đóng gói docker-compose + deploy VPS (mục 3.7)** — container webapp + playwright-mcp + `redis:alpine` + **caddy (TLS tự động)** (+ db), lên VPS + domain thật. Đăng ký thêm redirect URI cho domain thật ở Google/Azure. Caddy tự xin/gia hạn cert Let's Encrypt (không cần cronjob certbot).

**■ (bước 16-18):**
16. **Auto-forward theo `monitoring_mode`** (7.4) **[v0.9.9 đổi tên từ "theo Incoterm"]** — kèm whitelist + log. **[]**
17. **Transit & Vessel Rollover — toàn bộ §6.8** — bảng `shipment_legs` đã có ở schema (bước 2); phần build gồm: mở rộng Pydantic output Carrier ETA Agent để trích danh sách chặng (6.8a), gọi IMO Resolver cho từng leg + BullMQ repeatable job (6.8b), logic `switch_active_leg()` tín hiệu kép (6.8c), nối rollover vào Email Agent → tra lại IMO (6.8d). Ghi qua `resolve_leg()`/`switch_active_leg()` (1 transaction, mirror lên `shipments`). **[ cả 2 tuyến demo đi thẳng, không chạm transit; thiết kế-trước, không cam kết build.]**
18. **Cleanup job** — dọn `vessel_trail`/`eta_history`/`research_findings` sau 14 ngày kể từ `delivered_at` (4.9).

**Xuyên suốt:** **nhật ký build** — chụp màn hình từng bước, ghi cái gì chạy / cái gì lệch → nguồn cho mục 3.3.2 và 3.3.3 bài luận.

---

## 9. Giới hạn đã biết (ghi thẳng vào 3.3.3 bài luận)
- AIS free (terrestrial) phủ gần bờ, không ổn định giữa đại dương → giới hạn tuyến demo ở khu vực ngắn (cả 2 tuyến — nhập và xuất, mục 1.4). Không dùng satellite-AIS (trả phí).
- **[v0.9.9 — viết lại, trước là "thủy triều là bảng tĩnh"]** Thủy triều lấy từ **StormGlass tide** theo tọa độ cảng (geocode qua World Port Index), áp dụng được cho cảng bất kỳ — nhưng có 2 giới hạn phải nêu chủ động khi bảo vệ: **(a) datum** — mực nước trả về tương đối theo **MSL (Mean Sea Level)**, KHÔNG neo theo chart datum **LAT** mà hải đồ dùng tính UKC thực tế → đủ để minh họa logic "cảnh báo chờ con nước", không phải con số UKC hàng hải; **(b) cảng sông** — StormGlass tự chọn trạm gần tọa độ nhất nhưng không đảm bảo có trạm nằm sâu trong sông; với cảng như Cát Lái (cách biển ~50km theo sông Sài Gòn), trạm gần nhất khả năng cao ở ngoài cửa sông, không phản ánh đúng đặc tính triều trong sông. **Kết luận trình bày: đổi nguồn này giải quyết bài toán TỔNG QUÁT HÓA (chạy cho cảng bất kỳ, bỏ hardcode), KHÔNG cam kết chính xác hơn bảng tĩnh cũ tại đúng Cát Lái** — nhất quán ngôn ngữ "cảnh báo/ước lượng" (mục 6.3), không gọi "dự báo chính xác".
- **[v0.9.8] Phạm vi xuất chỉ mới bao C/D, chưa có xuất E/F:** hệ thống hiện không hỗ trợ hàng xuất Incoterm nhóm E/F (buyer nước ngoài lo main carriage, U&I không kiểm soát được luồng mail hãng tàu) — nếu nghiệp vụ phát sinh case này sau, cần thiết kế lại tương tự nhánh nhập C/D (qua trung gian/forward tay), không nằm trong phạm vi bản spec này.
- ETA là **cảnh báo ước lượng**, không phải dự báo tuyệt đối; hệ số Tầng 2 là ước lượng config, chưa hiệu chỉnh theo dữ liệu lịch sử (vì không train ML); chưa mô hình hóa thời gian xếp dỡ/chờ cầu bến.
- Chưa tích hợp hệ thống nội bộ U&I (TMS, CRM) và chưa nhận EDI thật — email mẫu mô phỏng.
- Agent email phụ thuộc chất lượng/định dạng email; có thể trích sai → nên mới có bước người duyệt.
- **[v0.9.9 — viết lại theo nguồn mới]** Dữ liệu thủy triều (StormGlass) chỉ 2 lần/ngày (free tier 10 call/ngày ÷ ~5 lô), không realtime như AIS — nhận định của Agent A về cửa sổ triều có thể dựa trên số liệu trễ tới 12h. Dòng chảy nay lấy từ Open-Meteo (không giới hạn call, cùng nhịp poll với wind/wave) nhưng là **dữ liệu mô hình đại dương** (Copernicus Marine), không phải quan trắc trực tiếp — vẫn giữ nhãn "ước lượng".
- **Phụ thuộc AG2 (framework bên thứ ba):** API còn thay đổi giữa các version → phải pin version cụ thể; là dependency nặng hơn so với tự viết tool-calling loop. Chấp nhận đánh đổi này để lấy phần điều phối 2 agent + retry/xử lý lỗi có sẵn (xem lý do ở mục 3.5).
- **Onboarding phụ thuộc web bên ngoài (VesselFinder + website hãng tàu):** cả hai có thể **đổi layout, chặn bot, bật CAPTCHA, hoặc bắt đăng nhập** → phân giải tự động có thể fail. Hai thành phần chịu rủi ro khác nhau: **(a) IMO Resolver** là script Playwright viết cứng (selector cố định, KHÔNG LLM) — ổn định khi VesselFinder giữ layout, nhưng **gãy cứng** nếu selector đổi (phải sửa code); **(b) Carrier ETA Agent** là agentic (LLM đọc trang qua Playwright MCP) — linh hoạt với nhiều layout hãng nhưng **tốn token** và **dễ vỡ** hơn. Giảm thiểu chung: cache `vessel_registry`, chạy một lần lúc tạo lô, và **fallback nhập tay** IMO/MMSI + `eta_original` (ghi `onboarding_error` + nút retry, mục 6.7) — nên onboarding không phải điểm chặn cứng của demo.
- **Trùng tên tàu:** nhiều tàu có thể cùng tên → IMO Resolver phân định bằng voyage/POL/POD (lọc trong code, không LLM), nhưng vẫn có khả năng chọn sai → kết quả kèm `confidence` + `source_url` để người dùng đối chiếu; case mơ hồ rơi về `manual_required`.
- **Thêm dependency hạ tầng Node/Chromium/Redis:** container `playwright-mcp` kéo theo Node + Chromium headless + BullMQ, cộng thêm container `redis:alpine` (~30-50MB idle) làm hàng đợi job → image nặng hơn, cần tài nguyên VPS. Tách container riêng để không lẫn vào image Python (ranh giới ngôn ngữ giải bằng HTTP `/scrape-jobs`, Python không chạm Redis), nhưng vẫn là chi phí vận hành đáng nêu. **MVP không lược Redis/BullMQ; semaphore-only chỉ là phương án ngoài MVP/scale-ahead.**
- **Build đa kiến trúc (cross-arch):** image Chromium phải khớp CPU của VPS đích → build bằng `docker buildx build --platform linux/amd64` hoặc dùng image nền `mcr.microsoft.com/playwright` (multi-arch, đã có sẵn Chromium + system libs) để tránh lỗi thiếu thư viện (libnss3/font/libatk) khi build trên máy ARM (Apple Silicon) rồi deploy lên VPS amd64.
- **Phát hiện transit phụ thuộc Carrier ETA Agent đọc đúng danh sách chặng (mục 6.8a):** phân loại `direct`/`transit` và trích chặng kế tiếp đều dựa trên việc LLM đọc đúng lịch trình từ website hãng → nếu hãng không công bố rõ chặng transshipment hoặc layout khó đọc, có thể phân loại sai (bỏ sót chặng → mất dấu tàu khi chuyển tàu). Giảm thiểu: fallback nhập tay danh sách chặng + nút retry; transit là [STRETCH], không chặn phần lõi.
- **Độ trễ chuyển leg active (tín hiệu kép, mục 6.8c):** việc chuyển tàu active chỉ xảy ra khi CẢ HAI tín hiệu khớp — Carrier ETA Agent xác định danh tính tàu chặng kế + AIS xác nhận tàu cũ đã rời cảng chuyển tải (tốc độ ~0 rồi tăng lại). Nếu AIS gần cảng chuyển tải chập chờn (giới hạn AIS free ở trên) hoặc agent tra chậm, có **độ trễ** trước khi hệ subscribe tàu mới → có thể mất vài giờ dữ liệu vị trí ở đầu chặng kế. Cố ý chọn tín hiệu kép (thay vì chuyển ngay khi agent báo) để tránh chuyển nhầm sang tàu chưa khởi hành — đánh đổi giữa độ trễ và độ chính xác, nêu rõ khi bảo vệ.
- **Rủi ro định dạng email auto-forward (mục 7.1/7.4):** nếu forward email hãng tàu vào mailbox hệ thống bằng kiểu Outlook "forward as attachment", nội dung gốc bị bọc trong lớp trích dẫn lồng nhau (nested quoted) → Email Agent phải bóc qua nhiều lớp mới trích được dữ liệu (số cont, voyage cũ→mới, ETA mới), dễ trích sai hơn. **Khuyến nghị dùng Gmail "true forwarding"** (giữ nguyên thân email) thay vì forward-as-attachment. Vẫn có bước người duyệt nên sai sót không tự cập nhật dữ liệu, nhưng định dạng xấu làm tăng tỷ lệ phải sửa tay.
- **Container lạ trong mail nhiều container bị bỏ qua im lặng (mục 7.1, v0.9.6):** khi một mail nhắc nhiều container, container không map được vào `shipments` nào chỉ được ghi log, KHÔNG tạo `agent_proposals` — đổi lại là tránh làm phình danh sách đề xuất bằng rác (mail của container không thuộc dự án, tin CC nhầm...), nhưng cũng có nghĩa một sai sót thật (VD lỗi chuẩn hoá số container khiến so khớp trượt) có thể bị bỏ sót thay vì được người dùng để ý và sửa tay. Chấp nhận đánh đổi này ở quy mô demo (3-5 lô, người dùng biết rõ lô nào đang theo dõi).
- **Xác thực & phân quyền (mục 3.8) — đủ cho audit, chưa đủ cho production siết chặt:** đã có OAuth Google/Microsoft (OIDC qua Authlib) + session JWT tự phát hành + `users`/`decided_by`/`verified_by` để trace *ai làm gì*. Nhưng: **(a) đăng ký MỞ** — mọi tài khoản Google/Microsoft đăng nhập được là tự tạo `user` (chưa giới hạn domain công ty, chưa có bước admin duyệt) → ở production thật cần siết bằng allowlist domain hoặc phê duyệt thủ công; **(b) phân quyền thô** (chỉ `user`/`admin`, chưa RBAC theo hành động); **(c) JWT tự ký** — cần quản lý secret qua env + đặt hạn/refresh hợp lý, chưa có revoke-list khi cần thu hồi phiên. Key LLM/aisstream cũng qua **biến môi trường** (mục 3.4), không commit. Nêu rõ đây là mức "đủ để định danh cho audit trail + chặn truy cập ẩn danh", không phải mô hình bảo mật doanh nghiệp đầy đủ.
- Research dựa trên search tin tức công khai — có thể bỏ sót tin (từ khóa không khớp) hoặc báo sai (tin không liên quan/tin cũ) → mọi phát hiện gắn nhãn "cần xác minh", không tự sửa ETA. Giới hạn cố hữu của LLM + web search cho tín hiệu định tính, cần nêu rõ khi bảo vệ.
- Trail + eta_history bị tự động xóa 14 ngày sau khi lô giao — cần export case study trước hạn nếu muốn dùng làm phụ lục.
- Quy mô nhỏ (3-5 lô): cố ý bám sát free tier, chưa kiểm chứng ở tải lớn.

Đây là phần thể hiện **trung thực học thuật** — nêu trước giới hạn giúp phòng thủ tốt khi bảo vệ.

---

## 10. Hướng phát triển tương lai (mục "future work" của bài luận)
- **ML dự đoán ETA** (học từ lịch sử hành trình + thời tiết, thay hệ số config bằng model học).
- **Satellite-AIS + API trả phí** (MarineTraffic, VesselFinder, Vizion, project44) để phủ tuyến dài xuyên đại dương — đồng thời **thay Vessel Resolver scrape web bằng API tra IMO/lịch trình chính thức** (ổn định hơn agentic browser, hết rủi ro CAPTCHA/đổi layout ở mục 9).
- **[v0.9.9 — sửa: realtime cơ bản đã giải quyết trong MVP bằng StormGlass tide]** **Thủy triều có datum offset theo chart datum (LAT) thực tế** khi có ngân sách/thời gian — thêm 1 hằng số offset chart-datum-to-MSL mỗi cảng (tra 1 lần từ hải đồ/tài liệu hải văn cảng) để con số UKC gần thực tế hơn, thay vì mực nước MSL thuần như MVP (giới hạn datum, mục 9).
- **[v0.9.9] Tầng dự phòng thủy triều offline (Tier 3):** tự tính triều tại tọa độ bất kỳ bằng **pyTMD** (NASA GSFC/UW APL, MIT license) đọc lưới hằng số triều toàn cầu **FES2014** (AVISO+) hoặc **TPXO9-atlas** (Oregon State) — không phụ thuộc mạng/API bên thứ ba lúc demo trực tiếp. Chỉ làm SAU khi Tier 1 (StormGlass) chạy ổn: cần đăng ký tải file NetCDF (nặng, nên lấy subset khu vực), cài thư viện, bọc FastAPI thành tool cho agent. Lưu ý: KHÔNG dùng U-tide/pytides cho việc này (hai thư viện đó fit hằng số từ chuỗi quan trắc trạm, không đọc lưới mô hình toàn cầu); và Tier 3 kế thừa nguyên giới hạn độ phân giải/cảng sông ở mục 9 — giải quyết "không phụ thuộc mạng", không giải quyết độ chính xác.
- **EDI thật (IFTSTA/IFTSAI)** + webhook hãng tàu thay cho đọc email.
- **Kafka + Flink** nếu scale lên hàng nghìn lô realtime, nhiều consumer.
- **Mở rộng số agent AG2** (thêm agent chuyên biệt, ví dụ agent phân tích cảng, agent dự báo chi phí) khi phát sinh nhu cầu — hiện MVP chỉ 2 agent A/B là đủ.
- **Vote / team-leader cho research** (nhiều agent research độc lập rồi tổng hợp bằng leader) — chỉ có giá trị khi cần tăng độ tin cậy ở quy mô lớn hoặc nhiều loại quyết định.
- **Tích hợp nội bộ** với TMS/CRM của U&I.

---

## 11. Việc cần xác minh khi thực tập (checklist)
- [x] U&I nhận thông báo rớt tàu/transit delay qua kênh nào thực tế (email sau đó sẽ delegate cho mail hệ thống, còn mail transit của nhập C/D CÓ THỂ và THỰC SỰ đi tới được mailbox hệ thống — chỉ là qua nhiều bước tay hơn E/F)
- [x] **[v0.9.8]** Phạm vi nghiệp vụ: hệ thống áp dụng cho **hàng nhập E/F, hàng nhập C/D, và hàng xuất C/D**. Hàng xuất C/D, U&I là bên bán, book tàu + nhận mail hãng tàu **trực tiếp** (không qua trung gian) → `monitoring_mode = auto_email`, cùng cơ chế với nhập E/F. Hàng xuất Incoterm nhóm E/F **ngoài phạm vi** (không hỗ trợ).

## 11b. Checklist tự kiểm trước khi coi là "chốt spec"
- [ ] **10 bảng thực thi** đủ cột/ràng buộc: 8 bảng nghiệp vụ §4 + `env_conditions` + `processed_emails` (IC§0.2); gồm vessel registry, users/audit và shipment legs.
- [ ] **Quy tắc mirror:** `shipments.onboarding_status`/`imo`/`mmsi`/`imo_resolved_via`/`onboarding_error` LUÔN là mirror của leg đang active trong `shipment_legs`; không có đường ghi tắt bỏ qua `shipment_legs`. Mọi cập nhật đi qua `resolve_leg()`/`switch_active_leg()`/`resolve_and_activate_leg()` (một transaction, KHÔNG dùng DB trigger). Transit & rollover.
- [ ] Mọi con số ETA đều truy vết được về công thức (Tầng 1 / Tầng 2), không có bước "hộp đen".
- [ ] Agent A/Agent B không có đường nào tự sửa `shipments`/`eta_current` — chỉ qua đề xuất + người duyệt/xác minh.
- [ ] IMO Resolver (6.7a) là script Playwright viết cứng, KHÔNG LLM/MCP; chỉ ghi `vessel_registry` + `imo_resolved_via` + set `onboarding_status`, KHÔNG đụng `eta_current`; có fallback `manual_required` + `onboarding_error` + retry, không crash/treo.
- [ ] Carrier ETA Agent (6.7b) là agent có LLM qua Playwright MCP; chỉ ghi `eta_original` + `eta_original_source`, KHÔNG đụng `eta_current`; fallback nhập tay.
- [ ] AIS worker + Agent A/B chỉ chạy cho lô `onboarding_status = resolved` (cổng trạng thái ở DB, không dùng handoff AG2).
- [ ] Auto-forward chỉ gửi tới whitelist nội bộ cấu hình trước, không lấy địa chỉ từ email đến.
- [ ] **[v0.9.6]** Email Agent dùng **HAI allowlist tách biệt** khi nhận mail (§7.4): (A) domain hãng tàu cho đường auto-forward thật, (B) địa chỉ người forward nội bộ (nhân viên U&I) cho đường manual-forward của C/D — không dùng một allowlist domain duy nhất (sẽ loại bỏ đúng mail forward tay hợp lệ).
- [ ] **[v0.9.6]** ETA Engine (§6.3) có guard ngưỡng SOG tối thiểu trước khi tính Tầng 1 (giữ ETA cũ khi tàu neo/cập cảng) VÀ guard `atd` khác null + `eta_original > atd` trước khi tính `deviation_pct` (bước 9b/10) — không chia cho tốc độ ≈0 hoặc mẫu số ≤0.
- [ ] **[v0.9.6]** Mail nhiều container (§7.1): container khớp shipment → tạo `agent_proposals` riêng; container lạ → chỉ log, không tạo proposal, không chặn container khớp còn lại trong cùng mail.
- [ ] **[v0.9.8]** `shipments` có cột `shipment_direction` (`import`\|`export`); `monitoring_mode` suy từ cặp `(shipment_direction, incoterm)` theo bảng §5 — KHÔNG suy 1 chiều từ `incoterm` đơn (nhập E/F=`auto_email`, nhập C/D=`manual`, xuất C/D=`auto_email`, xuất E/F=không hỗ trợ).
- [ ] **[v0.9.8]** UI tạo lô: chọn `shipment_direction` trước, dropdown Incoterm lọc theo direction — **ẩn nhóm E/F khi direction = export** (không cho chọn tổ hợp ngoài phạm vi).
- [ ] **[v0.9.8]** Allowlist (A) domain hãng tàu (§7.4) áp cho **mọi lô `auto_email`** (nhập E/F + xuất C/D), không riêng E/F; bảng forward §7.4 map theo `monitoring_mode`, không map thẳng theo nhóm chữ cái Incoterm.
- [ ] Ràng buộc free tier (Stormglass 10 call/ngày ↔ 5 lô × 2 call/ngày) nhất quán với số lô demo — **[v0.9.9]** quota này nay dành cho **tide** (không phải current; current đã chuyển sang Open-Meteo).
- [ ] **[v0.9.9]** Chuỗi hoán đổi nguồn nhất quán xuyên suốt spec: current/current-direction lấy từ **Open-Meteo** (`ocean_current_velocity`/`ocean_current_direction`, chung 1 lệnh gọi với wind/wave — §6.2/6.3); tide lấy từ **StormGlass** `/v2/tide/extremes/point` (§6.2/6.6); geocode cảng qua **World Port Index** offline (§6.6); không còn chỗ nào ghi "bảng thủy triều tĩnh" hay "current từ Stormglass" ngoài changelog/lịch sử.
- [ ] Cache research theo `route_key` + TTL 12h + cache `vessel_registry` theo tên tàu đã tính vào thiết kế (tránh search/scrape trùng).
- [ ] Layer 3 dùng AG2 (2 agent A/B) + IMO Resolver deterministic (script, không LLM) + Carrier ETA Agent qua Playwright MCP + Pydantic cho structured output; version AG2 + Playwright MCP + BullMQ đã pin.
- [ ] Ranh giới ngôn ngữ Python↔Node giải quyết bằng HTTP (`POST /scrape-jobs` + polling), Python KHÔNG chạm Redis/BullMQ trực tiếp (6.7d).
- [ ] Mọi hành động người-quyết-định đều trace được *ai làm*: `agent_proposals.decided_by` + `research_findings.verified_by` (FK `users.id`); duyệt/xác minh/nhập tay IMO/retry đều gắn user đang đăng nhập.
- [ ] Auth (mục 3.8) xong TRƯỚC khi deploy công khai (bước 14 trước 15); route ghi dữ liệu có middleware verify session; JWT tự phát hành (không dùng thẳng token provider); secret + key LLM/aisstream qua env. **OAuth flow có `state` (chống CSRF, Authlib lo) + PKCE. HAI cookie tách biệt, cả hai `HttpOnly` + `Secure` + `SameSite=Lax`, không `None` (cùng origin): (A) cookie handshake (SessionMiddleware, lưu `state`/`code_verifier`) BẮT BUỘC `Lax` — `Strict` sẽ chặn cookie ở callback top-level GET → gãy flow; (B) cookie JWT phiên (bước 6) chọn `Lax` vì HAI lý do cộng lại: request redirect ngay sau callback vẫn thuộc chuỗi navigation cross-site nên `Strict` có thể gãy flow lần đầu nếu redirect đáp vào route bảo vệ (dù cookie JWT chưa tồn tại lúc callback và các API call cùng origin sau đó không bị chặn), CỘNG trải nghiệm điều hướng-từ-ngoài (bookmark/link email tới route bảo vệ).**
- [ ] docker-compose có đủ container webapp + playwright-mcp + `redis:alpine` + `caddy` (TLS) (+ db); build cross-arch (`buildx --platform linux/amd64` hoặc image `mcr.microsoft.com/playwright`); MCP transport để HTTP/SSE (không stdio); key qua env, không commit.
- [ ] Các mục **[CẦN XÁC MINH]** được liệt kê để hỏi U&I trong kỳ thực tập.
- [ ] **[v0.9.12]** Mô hình chạy = **1 uvicorn worker** (background embedded qua lifespan, §3.1); Dockerfile CMD KHÔNG có `--workers >1`. Giới hạn multi-worker/multi-instance ghi ở §14.
- [ ] **[v0.9.12]** ETA Engine (§6.3): dấu deviation chốt (dương=trễ/âm=sớm), so góc current×COG có wrap-around 0/360 (`min(|a−b|,360−|a−b|)`), haversine gắn nhãn great-circle approximation.
- [ ] **[v0.9.12]** AIS worker hỗ trợ `AIS_MODE=live|replay` (§3.1/§6.2); replay dùng fixture, đi CÙNG đường xử lý upsert — phục vụ test/CI/E2E deterministic.

---

## 14. Known Limitations / Trước-production (blocker phải xử lý TRƯỚC khi scale — KHÔNG phải việc của demo)

> **[v0.9.12]** Mục này gom các giới hạn **cố ý chấp nhận ở demo** nhưng sẽ thành blocker khi đưa ra production/scale. Ghi rõ để (a) không ai nhầm "demo chạy được" = "sẵn sàng production", (b) khi bảo vệ trả lời được "hệ này scale thế nào". Đây KHÔNG phải việc build trong demo — chỉ là ranh giới đã tính trước.

- **Mô hình single-process (§3.1) — vỡ khi chạy multi-worker/multi-instance:** demo cố ý chạy **1 uvicorn worker duy nhất**, mọi background worker (AIS, trail snapshot, weather/tide poll, Agent A scheduler, email poll) embedded trong cùng process. Nếu chạy `uvicorn --workers >1` hoặc >1 instance (VD sau load-balancer), sẽ phát sinh: **duplicate AIS subscription** (mỗi process mở 1 WebSocket riêng, cùng subscribe → xử lý trùng bản tin), **duplicate email processing** (nhiều poller cùng fetch UNSEEN — dedup `processed_emails.message_id` chặn được trùng proposal nhưng vẫn tốn call LLM trùng + có race), **duplicate LLM call** (Agent A scheduler chạy nhiều bản), **duplicate proposal** (race giữa các process trước khi dedup commit). Ngoài ra **state in-memory sẽ vỡ**: mốc arrival first-seen của arrival detector (IC§0.3) và debounce recompute ETA (§6.3) giữ trong RAM của 1 process — nhiều process không thấy state của nhau. → **Trước production cần:** leader-election (chỉ 1 process chạy background) hoặc tách background thành **1 tiến trình đơn** riêng khỏi web workers, và đẩy state in-memory xuống Redis/DB. **KHÔNG thêm advisory lock / distributed lock / leader-election vào code demo** — đúng scope "right complexity".
- **Chỉ 1 email poller (§7.4):** email poll khởi động đúng 1 lần trong lifespan (nhất quán single-process trên). Nhiều poller song song cần locking/leader-election như trên — ghi ở đây, KHÔNG thêm lock vào demo.
- **Auth đăng ký MỞ + phân quyền thô (§3.8, §9):** đã ghi ở §9 — nhắc lại đây như blocker production: cần siết allowlist domain / duyệt admin, RBAC theo hành động, revoke-list JWT.
- **Phụ thuộc web scrape bên ngoài + free-tier API (§9):** VesselFinder/website hãng có thể chặn bot/CAPTCHA; StormGlass 10 call/ngày. Production cần API trả phí/EDI thật (§10 future work).
- **Migration forward-only (IC§2 / PROGRESS TASK-02):** MVP KHÔNG hỗ trợ `downgrade()` — mỗi thay đổi schema là 1 revision mới; rollback schema ở production cần thiết kế downgrade path riêng (hoặc restore backup).
- **[v0.9.13] Browser service tập trung (Browserless) là hướng scale-ahead (§6.7e), CHƯA build:** MVP để mỗi container `playwright-mcp` tự quản Chromium (BullMQ cap concurrency). Khi scale nhiều worker/máy, chuyển sang Browserless (remote CDP + queue/concurrency built-in) qua gateway `BrowserAgentClient`. Trước production cần: (a) verify bản `@playwright/mcp` đã pin có trỏ được remote CDP không (chưa xác nhận), (b) benchmark 3-5 session đồng thời, (c) kiểm license/operational. KHÔNG thêm Browserless adapter vào code demo.
