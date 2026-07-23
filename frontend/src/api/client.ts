export type ShipmentStatus = "new" | "on_sea" | "arrived" | "delivered";
export type ShipmentType = "direct" | "transit";
export type ShipmentDirection = "import" | "export";
export type MonitoringMode = "auto_email" | "manual";
export type OnboardingStatus = "pending" | "resolved" | "manual_required";
export type Incoterm = "EXW" | "FCA" | "FAS" | "FOB" | "CFR" | "CIF" | "CPT" | "CIP" | "DAP" | "DPU" | "DDP";

export interface ShipmentCreate {
  bl_number: string;
  container_no: string;
  shipment_direction: ShipmentDirection;
  incoterm: Incoterm;
  carrier: string;
  vessel_name: string;
  voyage_no: string;
  pol: string;
  pod: string;
  eta_original?: string | null;
  imo?: string | null;
  mmsi?: string | null;
}

export interface ShipmentListItem {
  id: number;
  bl_number: string;
  container_no: string;
  incoterm: Incoterm;
  shipment_direction: ShipmentDirection;
  carrier: string;
  vessel_name: string;
  voyage_no: string | null;
  pol: string;
  pod: string;
  status: ShipmentStatus;
  monitoring_mode: MonitoringMode;
  onboarding_status: OnboardingStatus;
  onboarding_error: string | null;
  eta_current: string | null;
  current_lat: number | null;
  current_lon: number | null;
  current_sog: number | null;
  current_cog: number | null;
  position_updated_at: string | null;
}

export interface ShipmentLeg {
  id: number;
  shipment_id: number;
  leg_no: number;
  vessel_name: string;
  voyage_no: string | null;
  imo: string | null;
  mmsi: string | null;
  imo_resolved_via: string | null;
  pol: string;
  pod: string;
  onboarding_status: OnboardingStatus;
  onboarding_error: string | null;
  is_active_leg: boolean;
  superseded_at: string | null;
  created_at: string;
}

export interface EtaHistory {
  id: number;
  shipment_id: number;
  eta_value: string;
  source: string;
  deviation_pct: number | null;
  note: string | null;
  recorded_at: string;
}

export interface TrailPoint {
  lat: number;
  lon: number;
  sog: number | null;
  recorded_at: string;
}

export interface EnvConditions {
  shipment_id: number;
  wind_speed_kn: number | null;
  wave_height_m: number | null;
  current_speed_kn: number | null;
  current_direction_deg: number | null;
  weather_fetched_at: string | null;
  tide_extremes: unknown[] | null;
  tide_station_name: string | null;
  tide_station_distance_km: number | null;
  tide_fetched_at: string | null;
}

export interface ShipmentDetail extends ShipmentListItem {
  imo: string | null;
  imo_resolved_via: string | null;
  mmsi: string | null;
  eta_original: string | null;
  eta_original_source: string | null;
  atd: string | null;
  shipment_type: ShipmentType;
  delivered_at: string | null;
  created_at: string;
  updated_at: string;
  legs: ShipmentLeg[];
  env: EnvConditions | null;
  recent_eta_history: EtaHistory[];
}

interface ApiErrorDetail {
  code?: string;
  message?: string;
}

export class ApiError extends Error {
  readonly status: number;
  readonly code?: string;
  readonly detail: unknown;

  constructor(status: number, message: string, code?: string, detail?: unknown) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
    this.detail = detail;
  }
}

const API_BASE = "/api/v1";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    ...init,
    credentials: "same-origin",
    headers: {
      ...(init?.body === undefined ? {} : { "Content-Type": "application/json" }),
      ...init?.headers,
    },
  });

  if (!response.ok) {
    let body: unknown;
    try {
      body = await response.json();
    } catch {
      body = undefined;
    }
    const detail = typeof body === "object" && body !== null && "detail" in body ? (body as { detail: unknown }).detail : body;
    const structured = typeof detail === "object" && detail !== null ? (detail as ApiErrorDetail) : undefined;
    const message = structured?.message ?? (typeof detail === "string" ? detail : response.statusText || `API request failed (${response.status})`);
    throw new ApiError(response.status, message, structured?.code, detail);
  }

  return response.json() as Promise<T>;
}

export interface ShipmentFilters {
  status?: ShipmentStatus;
  direction?: ShipmentDirection;
}

export function getShipments(filters: ShipmentFilters = {}): Promise<ShipmentListItem[]> {
  const params = new URLSearchParams();
  if (filters.status) params.set("status", filters.status);
  if (filters.direction) params.set("direction", filters.direction);
  const query = params.size > 0 ? `?${params.toString()}` : "";
  return request<ShipmentListItem[]>(`/shipments/${query}`);
}

export function getShipment(id: number): Promise<ShipmentDetail> {
  return request<ShipmentDetail>(`/shipments/${id}`);
}

export function getShipmentTrail(id: number): Promise<TrailPoint[]> {
  return request<TrailPoint[]>(`/shipments/${id}/trail`);
}

export function getShipmentEtaHistory(id: number): Promise<EtaHistory[]> {
  return request<EtaHistory[]>(`/shipments/${id}/eta-history`);
}

export function createShipment(shipment: ShipmentCreate): Promise<ShipmentDetail> {
  return request<ShipmentDetail>("/shipments/", {
    method: "POST",
    body: JSON.stringify(shipment),
  });
}

export type ProposalStatus = "pending" | "approved" | "rejected";

export interface ProposalExtracted {
  new_eta?: string | null;
  reason?: string | null;
  containers?: string[] | null;
  [key: string]: unknown;
}

export interface Proposal {
  id: number;
  shipment_id: number | null;
  source_email_id: string;
  extracted_json: ProposalExtracted | null;
  proposed_action: string | null;
  status: ProposalStatus;
  decided_by: number | null;
  created_at: string | null;
  decided_at: string | null;
}

export function getProposals(status: ProposalStatus = "pending"): Promise<Proposal[]> {
  return request<Proposal[]>(`/agent-proposals?status=${status}`);
}

export function approveProposal(id: number): Promise<Proposal> {
  return request<Proposal>(`/agent-proposals/${id}/approve`, { method: "POST" });
}

export function rejectProposal(id: number, reason?: string): Promise<Proposal> {
  return request<Proposal>(`/agent-proposals/${id}/reject`, {
    method: "POST",
    body: JSON.stringify({ reason: reason ?? null }),
  });
}
