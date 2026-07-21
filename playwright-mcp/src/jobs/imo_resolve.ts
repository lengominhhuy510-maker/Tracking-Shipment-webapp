// IMO Resolver — script Playwright CỨNG (Spec §6.7a): deterministic, KHÔNG LLM,
// KHÔNG MCP, KHÔNG ghi DB (IC§0.1 — Python validate + ghi qua resolve_leg()).
// Lỗi terminal ném Error có message BẮT ĐẦU bằng error_code (server.ts
// toErrorCode so startsWith) — không import ScrapeJobError từ queue.ts để
// tránh vòng import ESM.
import { chromium, type Browser, type BrowserContext } from "playwright";

export interface ImoResolvePayload {
  vessel_name: string;
  voyage_no?: string | null;
  pol?: string | null;
  pod?: string | null;
}

// Shape khớp IC§4.1 IMOResolverResult (Python validate lại bằng Pydantic)
export interface ImoResolverResult {
  vessel_name: string;
  imo: string; // ^\d{7}$
  mmsi: string | null; // ^\d{9}$
  matched_voyage: string | null;
  confidence: "cao" | "trung_binh" | "thap";
  source_url: string;
}

const VESSELFINDER_BASE = "https://www.vesselfinder.com";
const NAV_TIMEOUT_MS = 30_000;

// Trang search cấu trúc ổn định: mỗi kết quả là 1 anchor về trang chi tiết
// /vessels/details/<IMO 7 số>, tên tàu nằm trong .slna (fallback: text anchor).
const RESULT_LINK_SELECTOR = 'a[href*="/vessels/details/"]';
const DETAIL_IMO_RE = /\/vessels\/details\/(\d{7})/;
const MMSI_RE = /MMSI[^0-9]{0,40}(\d{9})/i;

let sharedBrowser: Browser | null = null;

async function getBrowser(): Promise<Browser> {
  if (!sharedBrowser || !sharedBrowser.isConnected()) {
    sharedBrowser = await chromium.launch({ headless: true });
  }
  return sharedBrowser;
}

function normalizeName(raw: string): string {
  return raw.trim().split(/\s+/).join(" ").toUpperCase();
}

function fail(code: "captcha" | "not_found" | "ambiguous_name" | "timeout" | "login_required", detail: string): never {
  throw new Error(`${code}: ${detail}`);
}

interface Candidate {
  imo: string;
  name: string;
  detailUrl: string;
}

async function detectBlocked(pageContent: string, pageUrl: string): Promise<void> {
  const lower = pageContent.toLowerCase();
  if (
    lower.includes("recaptcha") ||
    lower.includes("g-recaptcha") ||
    lower.includes("cf-challenge") ||
    lower.includes("challenge-platform") ||
    lower.includes("are you a human")
  ) {
    fail("captcha", "VesselFinder trả trang captcha/anti-bot");
  }
  if (pageUrl.includes("/login") || lower.includes("please log in to continue")) {
    fail("login_required", "VesselFinder yêu cầu đăng nhập");
  }
}

export async function runImoResolve(
  payload: ImoResolvePayload,
): Promise<ImoResolverResult> {
  const wanted = normalizeName(payload.vessel_name);
  const browser = await getBrowser();
  // 1 context riêng cho mỗi job — cô lập cookie/state, đóng trong finally.
  const context: BrowserContext = await browser.newContext({
    userAgent:
      "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36",
    viewport: { width: 1366, height: 900 },
  });
  try {
    const page = await context.newPage();
    page.setDefaultTimeout(NAV_TIMEOUT_MS);

    const searchUrl = `${VESSELFINDER_BASE}/vessels?name=${encodeURIComponent(wanted)}`;
    try {
      await page.goto(searchUrl, { waitUntil: "domcontentloaded" });
    } catch {
      fail("timeout", `không mở được ${searchUrl} trong ${NAV_TIMEOUT_MS}ms`);
    }
    await detectBlocked(await page.content(), page.url());

    // Đọc bảng kết quả bằng selector cố định (bước 2 §6.7a). Anchor textContent
    // gộp cả loại tàu ("EVER GIVEN CONTAINER SHIP") — ưu tiên .slna (chỉ tên).
    const rows = await page.$$eval(RESULT_LINK_SELECTOR, (anchors) =>
      anchors.map((a) => ({
        href: a.getAttribute("href") ?? "",
        text: (a.querySelector(".slna")?.textContent ?? a.textContent ?? "").trim(),
      })),
    );

    const candidateMap = new Map<string, Candidate>();
    for (const row of rows) {
      const match = DETAIL_IMO_RE.exec(row.href);
      if (!match || !row.text) continue;
      const imo = match[1];
      if (!candidateMap.has(imo)) {
        candidateMap.set(imo, {
          imo,
          name: normalizeName(row.text),
          detailUrl: new URL(row.href, VESSELFINDER_BASE).toString(),
        });
      }
    }
    const candidates = [...candidateMap.values()];
    if (candidates.length === 0) {
      fail("not_found", `không có kết quả cho ${wanted}`);
    }

    // Bước 3 §6.7a: lọc trùng tên bằng so chuỗi trong code — KHÔNG LLM.
    // Ưu tiên khớp tên chính xác; nhiều IMO khác nhau còn lại → ambiguous_name
    // (voyage không hiển thị trên VesselFinder nên không phân định thêm được).
    const exact = candidates.filter((c) => c.name === wanted);
    const filtered = exact.length > 0 ? exact : candidates;
    if (filtered.length > 1) {
      fail(
        "ambiguous_name",
        `${filtered.length} tàu trùng tên ${wanted}, voyage=${payload.voyage_no ?? "?"} không đủ phân định`,
      );
    }
    const chosen = filtered[0];
    const narrowed = candidates.length > 1;

    // Đọc MMSI từ trang chi tiết (không bắt buộc — null nếu không thấy).
    let mmsi: string | null = null;
    try {
      await page.goto(chosen.detailUrl, { waitUntil: "domcontentloaded" });
      const detailContent = await page.content();
      await detectBlocked(detailContent, page.url());
      mmsi = MMSI_RE.exec(detailContent)?.[1] ?? null;
    } catch (err) {
      if (err instanceof Error && /^(captcha|login_required):/.test(err.message)) {
        throw err;
      }
      mmsi = null; // chi tiết lỗi/chậm → vẫn trả IMO, MMSI để null
    }

    return {
      vessel_name: chosen.name,
      imo: chosen.imo,
      mmsi,
      matched_voyage: payload.voyage_no ?? null,
      confidence: narrowed ? "trung_binh" : "cao",
      source_url: chosen.detailUrl,
    };
  } finally {
    await context.close();
  }
}
