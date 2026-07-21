import type { OnboardingStatus, ShipmentDetail, ShipmentListItem, ShipmentStatus } from "./client";

interface WsEnvelope<T extends string, D> {
  type: T;
  shipment_id: number;
  ts: string;
  data: D;
}

interface PositionData {
  lat: number;
  lon: number;
  sog: number | null;
  cog: number | null;
  position_updated_at: string;
}

interface EtaData {
  eta_current: string;
  source: string;
  deviation_pct: number | null;
}

export interface DeviationAlertState {
  shipmentId: number;
  etaCurrent: string;
  etaOriginal: string;
  deviationPct: number;
  threshold: number;
  receivedAt: string;
}

export interface TidalAlertState {
  shipmentId: number;
  etaCurrent: string;
  nearestWindow: unknown;
  message: string;
  receivedAt: string;
}

export type ShipmentEvent =
  | WsEnvelope<"position_update", PositionData>
  | WsEnvelope<"eta_update", EtaData>
  | WsEnvelope<"deviation_alert", { eta_current: string; eta_original: string; deviation_pct: number; threshold: number }>
  | WsEnvelope<"tidal_alert", { eta_current: string; nearest_window: unknown; message: string }>
  | WsEnvelope<"proposal_created", { proposal_id: number; proposed_action: string }>
  | WsEnvelope<"onboarding_update", { onboarding_status: OnboardingStatus; onboarding_error: string | null; leg_id: number }>
  | WsEnvelope<"status_change", { old_status: ShipmentStatus; new_status: ShipmentStatus }>
  | WsEnvelope<"status_change_suggested", { suggested: "arrived"; reason: string }>;

export interface ShipmentRealtimeBindings {
  getShipments: () => ShipmentListItem[] | null;
  setShipments: (shipments: ShipmentListItem[]) => void;
  getOpenShipment: () => ShipmentDetail | null;
  setOpenShipment: (shipment: ShipmentDetail) => void;
  refetchShipments: () => Promise<void>;
  refetchOpenShipment: () => Promise<void>;
  setDeviationAlert: (alert: DeviationAlertState) => void;
  onTidalAlert?: (alert: TidalAlertState) => void;
  onProposalCreated?: (event: Extract<ShipmentEvent, { type: "proposal_created" }>) => void;
  onStatusChangeSuggested?: (event: Extract<ShipmentEvent, { type: "status_change_suggested" }>) => void;
}

export interface ShipmentRealtimeController {
  connect: () => void;
  close: () => void;
}

const knownTypes = new Set<ShipmentEvent["type"]>([
  "position_update",
  "eta_update",
  "deviation_alert",
  "tidal_alert",
  "proposal_created",
  "onboarding_update",
  "status_change",
  "status_change_suggested",
]);

function isEnvelope(value: unknown): value is ShipmentEvent {
  if (typeof value !== "object" || value === null) return false;
  const candidate = value as Partial<ShipmentEvent>;
  return typeof candidate.type === "string" && typeof candidate.shipment_id === "number" && typeof candidate.ts === "string" && typeof candidate.data === "object" && candidate.data !== null;
}

export function createShipmentRealtime(bindings: ShipmentRealtimeBindings): ShipmentRealtimeController {
  let socket: WebSocket | null = null;
  let reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  let reconnectDelayMs = 1_000;
  let deliberatelyClosed = false;
  let restReady = false;

  const updateKnownShipment = (
    shipmentId: number,
    update: (shipment: ShipmentListItem) => ShipmentListItem,
    detailUpdate?: (shipment: ShipmentDetail) => ShipmentDetail,
  ): boolean => {
    const shipments = bindings.getShipments();
    const detail = bindings.getOpenShipment();
    const inList = shipments?.some((shipment) => shipment.id === shipmentId) ?? false;
    const isOpen = detail?.id === shipmentId;

    if (!inList && !isOpen) return false;
    if (shipments && inList) {
      bindings.setShipments(shipments.map((shipment) => shipment.id === shipmentId ? update(shipment) : shipment));
    }
    if (detail && isOpen) {
      bindings.setOpenShipment(detailUpdate ? detailUpdate(detail) : { ...detail, ...update(detail) });
    }
    return true;
  };

  const dispatch = (event: ShipmentEvent): void => {
    if (!restReady) return;

    if (event.type === "proposal_created") {
      const isKnown = bindings.getShipments()?.some((shipment) => shipment.id === event.shipment_id)
        || bindings.getOpenShipment()?.id === event.shipment_id;
      bindings.onProposalCreated?.(event);
      if (!isKnown) void bindings.refetchShipments();
      return;
    }

    const knownLocally = bindings.getShipments()?.some((shipment) => shipment.id === event.shipment_id)
      || bindings.getOpenShipment()?.id === event.shipment_id;
    if (!knownLocally) return;

    switch (event.type) {
      case "position_update":
        updateKnownShipment(event.shipment_id, (shipment) => ({
          ...shipment,
          current_lat: event.data.lat,
          current_lon: event.data.lon,
          current_sog: event.data.sog,
          current_cog: event.data.cog,
          position_updated_at: event.data.position_updated_at,
        }));
        break;
      case "eta_update":
        updateKnownShipment(event.shipment_id, (shipment) => ({ ...shipment, eta_current: event.data.eta_current }));
        break;
      case "deviation_alert":
        updateKnownShipment(event.shipment_id, (shipment) => ({ ...shipment, eta_current: event.data.eta_current }));
        bindings.setDeviationAlert({
          shipmentId: event.shipment_id,
          etaCurrent: event.data.eta_current,
          etaOriginal: event.data.eta_original,
          deviationPct: event.data.deviation_pct,
          threshold: event.data.threshold,
          receivedAt: event.ts,
        });
        break;
      case "tidal_alert":
        updateKnownShipment(event.shipment_id, (shipment) => ({ ...shipment, eta_current: event.data.eta_current }));
        bindings.onTidalAlert?.({
          shipmentId: event.shipment_id,
          etaCurrent: event.data.eta_current,
          nearestWindow: event.data.nearest_window,
          message: event.data.message,
          receivedAt: event.ts,
        });
        break;
      case "onboarding_update":
        updateKnownShipment(
          event.shipment_id,
          (shipment) => ({
            ...shipment,
            onboarding_status: event.data.onboarding_status,
            onboarding_error: event.data.onboarding_error,
          }),
          (shipment) => ({
            ...shipment,
            onboarding_status: event.data.onboarding_status,
            onboarding_error: event.data.onboarding_error,
            legs: shipment.legs.map((leg) => leg.id === event.data.leg_id ? {
              ...leg,
              onboarding_status: event.data.onboarding_status,
              onboarding_error: event.data.onboarding_error,
            } : leg),
          }),
        );
        break;
      case "status_change":
        updateKnownShipment(event.shipment_id, (shipment) => ({ ...shipment, status: event.data.new_status }));
        break;
      case "status_change_suggested":
        bindings.onStatusChangeSuggested?.(event);
        break;
    }
  };

  const scheduleReconnect = (): void => {
    if (deliberatelyClosed || reconnectTimer !== null) return;
    const delay = reconnectDelayMs;
    reconnectDelayMs = Math.min(reconnectDelayMs * 2, 30_000);
    reconnectTimer = setTimeout(() => {
      reconnectTimer = null;
      connect();
    }, delay);
  };

  const connect = (): void => {
    if (socket && (socket.readyState === WebSocket.OPEN || socket.readyState === WebSocket.CONNECTING)) return;
    deliberatelyClosed = false;
    restReady = false;
    const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
    socket = new WebSocket(`${protocol}//${window.location.host}/ws`);

    socket.onopen = () => {
      reconnectDelayMs = 1_000;
      void Promise.all([
        bindings.refetchShipments(),
        bindings.refetchOpenShipment(),
      ]).then(() => {
        if (socket?.readyState === WebSocket.OPEN) restReady = true;
      }).catch((error: unknown) => {
        console.warn("REST refetch failed after WebSocket open", error);
        socket?.close();
      });
    };
    socket.onmessage = (message) => {
      let parsed: unknown;
      try {
        parsed = JSON.parse(String(message.data));
      } catch {
        console.warn("Ignoring malformed WebSocket message");
        return;
      }
      if (!isEnvelope(parsed)) {
        console.warn("Ignoring malformed WebSocket envelope", parsed);
        return;
      }
      if (!knownTypes.has(parsed.type)) {
        console.warn(`Ignoring unknown WebSocket event type: ${parsed.type}`);
        return;
      }
      dispatch(parsed);
    };
    socket.onclose = () => {
      socket = null;
      restReady = false;
      scheduleReconnect();
    };
    socket.onerror = () => {
      socket?.close();
    };
  };

  const close = (): void => {
    deliberatelyClosed = true;
    restReady = false;
    if (reconnectTimer !== null) {
      clearTimeout(reconnectTimer);
      reconnectTimer = null;
    }
    const activeSocket = socket;
    socket = null;
    activeSocket?.close();
  };

  return { connect, close };
}
