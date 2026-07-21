# Deploy VPS — runbook (TASK-15)

Đóng gói 5 container (`caddy`, `webapp`, `playwright-mcp`, `db`, `redis`) qua
`infra/docker-compose.yml`. Base compose file **production-safe**: chỉ `caddy`
map port ra host (80/443); `webapp`/`db`/`redis`/`playwright-mcp` chỉ nằm trên
network nội bộ.

## 1. Chuẩn bị VPS

- VPS Linux amd64, cài Docker Engine + Docker Compose plugin.
- DNS: trỏ A record `{domain}` → IP VPS (bắt buộc cho Let's Encrypt auto-TLS).
- Mở firewall inbound 80 + 443 (chỉ 2 port này).

## 2. Điền `.env` production (gốc repo)

```bash
cp .env.example .env
```

Bắt buộc chỉnh:

| Biến | Giá trị production |
|---|---|
| `DOMAIN` | domain thật, ví dụ `tracking.example.com` — Caddy dùng cho auto-TLS |
| `APP_BASE_URL` | `https://{DOMAIN}` |
| `COOKIE_SECURE` | **`true`** (cookie session chỉ đi qua HTTPS) |
| `SESSION_JWT_SECRET` | secret ngẫu nhiên mạnh (ví dụ `openssl rand -hex 32`) |
| `GOOGLE_CLIENT_ID/SECRET`, `MICROSOFT_CLIENT_ID/SECRET` | OAuth credentials |
| Các API key còn lại | `AISSTREAM_API_KEY`, `STORMGLASS_API_KEY`, `LLM_*`, `SEARCH_API_KEY`, mailbox... |

Không commit `.env` (đã gitignore).

## 3. Đăng ký redirect URI production

Vào Google Cloud Console + Azure App Registration, **thêm** (không bỏ localhost):

```
https://{domain}/auth/callback/google
https://{domain}/auth/callback/microsoft
```

Giữ nguyên URI `http://localhost:1476/...` để dev tiếp tục hoạt động.

## 4. Build cross-arch (khi build từ máy không phải amd64)

VPS chạy linux/amd64; build từ máy dev (Windows/Mac ARM) phải chỉ định platform:

```bash
docker buildx build --platform linux/amd64 -f backend/Dockerfile -t webapp .
docker buildx build --platform linux/amd64 -t playwright-mcp ./playwright-mcp
```

Build trực tiếp trên VPS amd64 thì `docker compose up --build` là đủ.

## 5. Chạy stack

```bash
docker compose -f infra/docker-compose.yml up -d --build
```

- Caddy tự xin cert Let's Encrypt cho `DOMAIN` (cần DNS đã trỏ + port 80/443 mở).
- `webapp` có healthcheck `/api/v1/health` (chấp nhận 200/401 — 401 nghĩa là
  server sống nhưng chưa có cookie); caddy chỉ start khi webapp healthy.
- Production KHÔNG map `webapp` ra host. Dev local muốn truy cập trực tiếp
  `localhost:1476`:

```bash
docker compose -f infra/docker-compose.yml -f infra/docker-compose.dev.yml up --build
```

## 6. Kiểm tra sau deploy

```bash
docker compose -f infra/docker-compose.yml ps          # 5 service healthy
curl -k https://{domain}/api/v1/health                  # 401 JSON (chưa cookie) = OK
```

Mở `https://{domain}` → trang login (FE build tĩnh phục vụ từ webapp qua caddy);
login OAuth → app hiện; F5 ở route con không 404 (SPA fallback).

## 7. Vận hành

```bash
docker compose -f infra/docker-compose.yml logs -f webapp   # log app
docker compose -f infra/docker-compose.yml pull && \
docker compose -f infra/docker-compose.yml up -d --build    # cập nhật
```

Dữ liệu bền: volume `db_data` (postgres), `caddy_data` (cert). Backup postgres:

```bash
docker compose -f infra/docker-compose.yml exec db pg_dump -U app shipment_demo > backup.sql
```
