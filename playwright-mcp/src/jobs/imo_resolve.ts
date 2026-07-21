// Placeholder job handler — script Playwright VesselFinder THẬT thuộc TASK-11.
// TASK-10 chỉ dựng luồng queue: nhận payload, trả kết quả giả đúng shape
// IMOResolverResult (IC§4.1) để test enqueue → worker → poll end-to-end.

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

export async function runImoResolve(
  payload: ImoResolvePayload,
): Promise<ImoResolverResult> {
  // TASK-11 thay bằng: browser.newContext() riêng cho job này → tra VesselFinder
  // → đóng context trong finally. Placeholder trả dữ liệu giả deterministic.
  return {
    vessel_name: payload.vessel_name,
    imo: "9999999",
    mmsi: null,
    matched_voyage: payload.voyage_no ?? null,
    confidence: "thap",
    source_url: "https://example.com/placeholder-task-11",
  };
}
