// QA-07 — WS 8 event + reconnect policy + milestone map (REPORT-ONLY).
//
// Truth:
//   IC§6   — envelope shape + 8-type table + 8 broadcast_* mapping.
//   IC§6.1 — 7 client policy points (REST=truth, idempotent dispatch, unknown
//            type ignored, exponential backoff cap 30s, refetch on (re)open
//            before delta, unknown-shipment handling, event-before-REST safe).
//   IC§1.2 — milestone map derived from (status, atd, shipment_type), 5 rows.
//
// App code is NOT modified. ws.ts and milestone.ts are exercised through their
// public surface only. ws.ts depends on the browser globals `window` and
// `WebSocket`; vitest runs in the node environment, so this file installs a
// deterministic in-memory MockWebSocket + a stub window (no real network).

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { ShipmentDetail, ShipmentLeg, ShipmentListItem } from "../../src/api/client";
import { createShipmentRealtime, type ShipmentRealtimeBindings } from "../../src/api/ws";
import { statusToMilestone } from "../../src/milestone";

// ---------------------------------------------------------------------------
// Deterministic MockWebSocket — drives ws.ts onopen/onmessage/onclose by hand.
// ---------------------------------------------------------------------------
class MockWebSocket {
  static CONNECTING = 0 as const;
  static OPEN = 1 as const;
  static CLOSING = 2 as const;
  static CLOSED = 3 as const;
  static instances: MockWebSocket[] = [];

  url: string;
  readyState: number = MockWebSocket.CONNECTING;
  onopen: (() => void) | null = null;
  onmessage: ((ev: { data: string }) => void) | null = null;
  onclose: (() => void) | null = null;
  onerror: (() => void) | null = null;
  close = vi.fn(() => {
    this.readyState = MockWebSocket.CLOSED;
  });

  constructor(url: string) {
    this.url = url;
    MockWebSocket.instances.push(this);
  }

  static latest(): MockWebSocket {
    const ws = MockWebSocket.instances.at(-1);
    if (!ws) throw new Error("no MockWebSocket created");
    return ws;
  }
}

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
}

// Drain the microtask queue (Promise is NOT faked by vi.useFakeTimers()).
async function flush(): Promise<void> {
  for (let i = 0; i < 6; i += 1) await Promise.resolve();
}

// ---------------------------------------------------------------------------
// Fixtures / bindings
// ---------------------------------------------------------------------------
function baseShipment(id: number): ShipmentListItem {
  return {
    id,
    bl_number: `BL${id}`,
    container_no: "MSCU1234567",
    incoterm: "FOB",
    shipment_direction: "import",
    carrier: "MSC",
    vessel_name: "EVER GIVEN",
    voyage_no: "001E",
    pol: "SGSIN",
    pod: "VNSGN",
    status: "on_sea",
    monitoring_mode: "auto_email",
    onboarding_status: "resolved",
    onboarding_error: null,
    eta_current: "2026-07-30T00:00:00Z",
    current_lat: null,
    current_lon: null,
    current_sog: null,
    current_cog: null,
    position_updated_at: null,
  };
}

function baseDetail(id: number): ShipmentDetail {
  const leg: ShipmentLeg = {
    id: 10,
    shipment_id: id,
    leg_no: 1,
    vessel_name: "EVER GIVEN",
    voyage_no: "001E",
    imo: "9811000",
    mmsi: "570000001",
    imo_resolved_via: "manual",
    pol: "SGSIN",
    pod: "VNSGN",
    onboarding_status: "resolved",
    onboarding_error: null,
    is_active_leg: true,
    superseded_at: null,
    created_at: "2026-07-20T00:00:00Z",
  };
  return {
    ...baseShipment(id),
    imo: "9811000",
    imo_resolved_via: "manual",
    mmsi: "570000001",
    eta_original: "2026-07-29T00:00:00Z",
    eta_original_source: "original",
    atd: "2026-07-21T00:00:00Z",
    shipment_type: "direct",
    delivered_at: null,
    created_at: "2026-07-20T00:00:00Z",
    updated_at: "2026-07-21T00:00:00Z",
    legs: [leg],
    env: null,
    recent_eta_history: [],
  };
}

interface BindingsInit {
  shipments?: ShipmentListItem[] | null;
  detail?: ShipmentDetail | null;
  refetchShipments?: () => Promise<void>;
  refetchOpenShipment?: () => Promise<void>;
}

function makeBindings(init: BindingsInit = {}): ShipmentRealtimeBindings {
  let shipments: ShipmentListItem[] | null =
    init.shipments === undefined ? [baseShipment(1)] : init.shipments;
  let detail: ShipmentDetail | null = init.detail ?? null;
  return {
    getShipments: () => shipments,
    setShipments: vi.fn((next: ShipmentListItem[]) => {
      shipments = next;
    }),
    getOpenShipment: () => detail,
    setOpenShipment: vi.fn((next: ShipmentDetail) => {
      detail = next;
    }),
    refetchShipments: init.refetchShipments ?? vi.fn(() => Promise.resolve()),
    refetchOpenShipment: init.refetchOpenShipment ?? vi.fn(() => Promise.resolve()),
    setDeviationAlert: vi.fn(),
    onTidalAlert: vi.fn(),
    onProposalCreated: vi.fn(),
    onStatusChangeSuggested: vi.fn(),
  };
}

function envelope(type: string, shipmentId: number, data: unknown): string {
  return JSON.stringify({ type, shipment_id: shipmentId, ts: "2026-07-22T09:30:00Z", data });
}

function positionData() {
  return { lat: 10, lon: 20, sog: 12.5, cog: 90, position_updated_at: "2026-07-22T09:30:00Z" };
}

async function connectReady(ctrl: { connect: () => void }): Promise<MockWebSocket> {
  ctrl.connect();
  const ws = MockWebSocket.latest();
  ws.readyState = MockWebSocket.OPEN;
  ws.onopen?.();
  await flush();
  return ws;
}

let warnSpy: ReturnType<typeof vi.spyOn>;

beforeEach(() => {
  vi.useFakeTimers();
  MockWebSocket.instances = [];
  (globalThis as unknown as { WebSocket: unknown }).WebSocket = MockWebSocket;
  (globalThis as unknown as { window: unknown }).window = {
    location: { protocol: "http:", host: "localhost:1476" },
  };
  warnSpy = vi.spyOn(console, "warn").mockImplementation(() => {});
});

afterEach(() => {
  warnSpy.mockRestore();
  vi.useRealTimers();
  delete (globalThis as unknown as { WebSocket?: unknown }).WebSocket;
  delete (globalThis as unknown as { window?: unknown }).window;
});

// ===========================================================================
// 1. IC§6 — 8 WS types recognised on the client (1-1 with broadcast table).
// ===========================================================================
describe("IC§6 — 8 WS event types (frontend knownTypes 1-1)", () => {
  const EIGHT_TYPES = [
    "position_update",
    "eta_update",
    "deviation_alert",
    "tidal_alert",
    "proposal_created",
    "onboarding_update",
    "status_change",
    "status_change_suggested",
  ] as const;

  it("accepts every one of the 8 IC§6 types without an 'unknown type' warning", async () => {
    const ctrl = createShipmentRealtime(makeBindings());
    const ws = await connectReady(ctrl);
    for (const type of EIGHT_TYPES) {
      warnSpy.mockClear();
      ws.onmessage?.({ data: envelope(type, 1, {}) });
      const unknownWarned = warnSpy.mock.calls.some((c) =>
        String(c[0]).includes("unknown WebSocket event type"),
      );
      expect(unknownWarned, `${type} must be a known type`).toBe(false);
    }
    ctrl.close();
  });

  it("has exactly 8 recognised types (a 9th, drifted name is rejected)", async () => {
    const ctrl = createShipmentRealtime(makeBindings());
    const ws = await connectReady(ctrl);
    // A near-miss / drifted name (one char off) must be treated as unknown.
    ws.onmessage?.({ data: envelope("position_updated", 1, positionData()) });
    expect(
      warnSpy.mock.calls.some((c) => String(c[0]).includes("unknown WebSocket event type")),
    ).toBe(true);
    ctrl.close();
  });
});

// ===========================================================================
// 2. IC§6.1 point 3 — unknown type + malformed input → log + skip, no crash.
// ===========================================================================
describe("IC§6.1(3) — unknown type / malformed → log + skip, never crash", () => {
  it("unknown type is logged and ignored (no state mutation, no throw)", async () => {
    const bindings = makeBindings();
    const ctrl = createShipmentRealtime(bindings);
    const ws = await connectReady(ctrl);
    expect(() => ws.onmessage?.({ data: envelope("brand_new_event_v2", 1, { x: 1 }) })).not.toThrow();
    expect(
      warnSpy.mock.calls.some((c) => String(c[0]).includes("unknown WebSocket event type")),
    ).toBe(true);
    expect(bindings.setShipments).not.toHaveBeenCalled();
    ctrl.close();
  });

  it("malformed JSON is logged and ignored", async () => {
    const bindings = makeBindings();
    const ctrl = createShipmentRealtime(bindings);
    const ws = await connectReady(ctrl);
    expect(() => ws.onmessage?.({ data: "}{not json" })).not.toThrow();
    expect(
      warnSpy.mock.calls.some((c) => String(c[0]).includes("malformed WebSocket message")),
    ).toBe(true);
    expect(bindings.setShipments).not.toHaveBeenCalled();
    ctrl.close();
  });

  it("valid JSON but non-envelope shape is logged and ignored", async () => {
    const bindings = makeBindings();
    const ctrl = createShipmentRealtime(bindings);
    const ws = await connectReady(ctrl);
    expect(() => ws.onmessage?.({ data: JSON.stringify({ foo: "bar" }) })).not.toThrow();
    expect(
      warnSpy.mock.calls.some((c) => String(c[0]).includes("malformed WebSocket envelope")),
    ).toBe(true);
    expect(bindings.setShipments).not.toHaveBeenCalled();
    ctrl.close();
  });
});

// ===========================================================================
// 3. IC§6.1 point 6 — event for shipment NOT in local state.
// ===========================================================================
describe("IC§6.1(6) — event for a shipment_id not in local state", () => {
  it("position_update for an unknown shipment is skipped (waits for refetch)", async () => {
    const bindings = makeBindings({ shipments: [baseShipment(1)], detail: null });
    const ctrl = createShipmentRealtime(bindings);
    const ws = await connectReady(ctrl);
    (bindings.setShipments as ReturnType<typeof vi.fn>).mockClear();
    ws.onmessage?.({ data: envelope("position_update", 999, positionData()) });
    expect(bindings.setShipments).not.toHaveBeenCalled();
    ctrl.close();
  });

  it("eta/deviation/status events for an unknown shipment do not fire their side effects", async () => {
    const bindings = makeBindings({ shipments: [baseShipment(1)], detail: null });
    const ctrl = createShipmentRealtime(bindings);
    const ws = await connectReady(ctrl);
    (bindings.setShipments as ReturnType<typeof vi.fn>).mockClear();
    ws.onmessage?.({ data: envelope("eta_update", 999, { eta_current: "x", source: "s", deviation_pct: null }) });
    ws.onmessage?.({ data: envelope("deviation_alert", 999, { eta_current: "x", eta_original: "y", deviation_pct: 30, threshold: 10 }) });
    ws.onmessage?.({ data: envelope("status_change", 999, { old_status: "on_sea", new_status: "arrived" }) });
    expect(bindings.setShipments).not.toHaveBeenCalled();
    expect(bindings.setDeviationAlert).not.toHaveBeenCalled();
    ctrl.close();
  });

  it("proposal_created for an unknown shipment refetches the list (pull new lot)", async () => {
    const refetchShipments = vi.fn(() => Promise.resolve());
    const bindings = makeBindings({ shipments: [baseShipment(1)], detail: null, refetchShipments });
    const ctrl = createShipmentRealtime(bindings);
    const ws = await connectReady(ctrl);
    const baseline = refetchShipments.mock.calls.length; // 1 from onopen
    ws.onmessage?.({ data: envelope("proposal_created", 999, { proposal_id: 5, proposed_action: "rollover" }) });
    await flush();
    expect(refetchShipments.mock.calls.length).toBe(baseline + 1);
    expect(bindings.onProposalCreated).toHaveBeenCalledTimes(1);
    ctrl.close();
  });

  it("proposal_created for a KNOWN shipment does NOT refetch the list", async () => {
    const refetchShipments = vi.fn(() => Promise.resolve());
    const bindings = makeBindings({ shipments: [baseShipment(1)], detail: null, refetchShipments });
    const ctrl = createShipmentRealtime(bindings);
    const ws = await connectReady(ctrl);
    const baseline = refetchShipments.mock.calls.length;
    ws.onmessage?.({ data: envelope("proposal_created", 1, { proposal_id: 5, proposed_action: "rollover" }) });
    await flush();
    expect(refetchShipments.mock.calls.length).toBe(baseline); // no extra refetch
    expect(bindings.onProposalCreated).toHaveBeenCalledTimes(1);
    ctrl.close();
  });
});

// ===========================================================================
// 4. IC§6.1 point 2 — idempotent dispatch (duplicate event → same result).
// ===========================================================================
describe("IC§6.1(2) — idempotent dispatch", () => {
  it("applying the same position_update twice yields identical state", async () => {
    const bindings = makeBindings({ shipments: [baseShipment(1)], detail: null });
    const ctrl = createShipmentRealtime(bindings);
    const ws = await connectReady(ctrl);

    ws.onmessage?.({ data: envelope("position_update", 1, positionData()) });
    const afterOnce = JSON.stringify(bindings.getShipments());

    ws.onmessage?.({ data: envelope("position_update", 1, positionData()) });
    const afterTwice = JSON.stringify(bindings.getShipments());

    expect(afterTwice).toBe(afterOnce);
    const ship = bindings.getShipments()?.[0];
    expect(ship?.current_lat).toBe(10);
    expect(ship?.current_lon).toBe(20);
    ctrl.close();
  });

  it("applying the same status_change twice yields identical state", async () => {
    const bindings = makeBindings({ shipments: [baseShipment(1)], detail: null });
    const ctrl = createShipmentRealtime(bindings);
    const ws = await connectReady(ctrl);
    ws.onmessage?.({ data: envelope("status_change", 1, { old_status: "on_sea", new_status: "arrived" }) });
    const once = JSON.stringify(bindings.getShipments());
    ws.onmessage?.({ data: envelope("status_change", 1, { old_status: "on_sea", new_status: "arrived" }) });
    const twice = JSON.stringify(bindings.getShipments());
    expect(twice).toBe(once);
    expect(bindings.getShipments()?.[0].status).toBe("arrived");
    ctrl.close();
  });
});

// ===========================================================================
// 5. IC§6.1 points 1/5/7 — refetch list+detail on (re)open BEFORE delta.
// ===========================================================================
describe("IC§6.1(1,5,7) — REST-first: refetch on open before listening to delta", () => {
  it("onopen refetches list + detail; deltas before REST resolves are ignored", async () => {
    const rs = deferred<void>();
    const rd = deferred<void>();
    const refetchShipments = vi.fn(() => rs.promise);
    const refetchOpenShipment = vi.fn(() => rd.promise);
    const bindings = makeBindings({
      shipments: [baseShipment(1)],
      detail: null,
      refetchShipments,
      refetchOpenShipment,
    });
    const ctrl = createShipmentRealtime(bindings);
    ctrl.connect();
    const ws = MockWebSocket.latest();
    ws.readyState = MockWebSocket.OPEN;
    ws.onopen?.();

    // Refetch of both list + detail is triggered immediately on open (point 5).
    expect(refetchShipments).toHaveBeenCalledTimes(1);
    expect(refetchOpenShipment).toHaveBeenCalledTimes(1);

    // A delta arriving BEFORE REST resolves is safely ignored (point 7).
    ws.onmessage?.({ data: envelope("position_update", 1, positionData()) });
    await flush();
    expect(bindings.setShipments).not.toHaveBeenCalled();

    // Once REST resolves, deltas are applied (point 1: REST = source of truth).
    rs.resolve();
    rd.resolve();
    await flush();
    ws.onmessage?.({ data: envelope("position_update", 1, positionData()) });
    await flush();
    expect(bindings.setShipments).toHaveBeenCalledTimes(1);
    ctrl.close();
  });

  it("reconnect (second onopen) refetches list + detail again", async () => {
    const refetchShipments = vi.fn(() => Promise.resolve());
    const refetchOpenShipment = vi.fn(() => Promise.resolve());
    const bindings = makeBindings({ shipments: [baseShipment(1)], detail: null, refetchShipments, refetchOpenShipment });
    const ctrl = createShipmentRealtime(bindings);

    let ws = await connectReady(ctrl);
    expect(refetchShipments).toHaveBeenCalledTimes(1);
    expect(refetchOpenShipment).toHaveBeenCalledTimes(1);

    // Server drops the connection.
    ws.readyState = MockWebSocket.CLOSED;
    ws.onclose?.();
    // Backoff timer fires → reconnect.
    vi.advanceTimersByTime(1_000);
    ws = MockWebSocket.latest();
    ws.readyState = MockWebSocket.OPEN;
    ws.onopen?.();
    await flush();

    expect(refetchShipments).toHaveBeenCalledTimes(2);
    expect(refetchOpenShipment).toHaveBeenCalledTimes(2);
    ctrl.close();
  });
});

// ===========================================================================
// 6. IC§6.1 point 4 — exponential backoff 1→2→4→8→16→cap 30s.
// ===========================================================================
describe("IC§6.1(4) — reconnect exponential backoff, cap 30s", () => {
  it("doubles the delay each failed connect and caps at 30000ms", () => {
    const setTimeoutSpy = vi.spyOn(globalThis, "setTimeout");
    const ctrl = createShipmentRealtime(makeBindings());
    ctrl.connect();

    const delays: number[] = [];
    for (let i = 0; i < 8; i += 1) {
      const ws = MockWebSocket.latest();
      ws.readyState = MockWebSocket.CLOSED;
      ws.onclose?.(); // schedules reconnect with the current delay
      const lastCall = setTimeoutSpy.mock.calls.at(-1);
      const delay = Number(lastCall?.[1]);
      delays.push(delay);
      vi.advanceTimersByTime(delay); // fire reconnect → new socket
    }

    expect(delays).toEqual([1000, 2000, 4000, 8000, 16000, 30000, 30000, 30000]);
    ctrl.close();
    setTimeoutSpy.mockRestore();
  });

  it("resets backoff to 1s after a successful open", async () => {
    const setTimeoutSpy = vi.spyOn(globalThis, "setTimeout");
    const ctrl = createShipmentRealtime(makeBindings());

    // First connect fails twice → delay grows to 2s.
    ctrl.connect();
    let ws = MockWebSocket.latest();
    ws.readyState = MockWebSocket.CLOSED;
    ws.onclose?.();
    let delay = Number(setTimeoutSpy.mock.calls.at(-1)?.[1]);
    expect(delay).toBe(1000);
    vi.advanceTimersByTime(delay);

    ws = MockWebSocket.latest();
    ws.readyState = MockWebSocket.CLOSED;
    ws.onclose?.();
    delay = Number(setTimeoutSpy.mock.calls.at(-1)?.[1]);
    expect(delay).toBe(2000);
    vi.advanceTimersByTime(delay);

    // Now a successful open resets the backoff.
    ws = MockWebSocket.latest();
    ws.readyState = MockWebSocket.OPEN;
    ws.onopen?.();
    await flush();

    // Next drop schedules with the reset 1s delay again.
    ws.readyState = MockWebSocket.CLOSED;
    ws.onclose?.();
    delay = Number(setTimeoutSpy.mock.calls.at(-1)?.[1]);
    expect(delay).toBe(1000);

    ctrl.close();
    setTimeoutSpy.mockRestore();
  });
});

// ===========================================================================
// 7. IC§1.2 — milestone map from (status, atd, shipment_type), 5 rows.
// ===========================================================================
describe("IC§1.2 — milestone map (all 5 rows)", () => {
  it("row 1: new / atd NULL / any → [Nhận B/L] current, departed not completed", () => {
    const m = statusToMilestone("new", true, "direct");
    expect(m.current.id).toBe("received_bl");
    expect(m.nodes.map((n) => n.id)).toEqual(["received_bl", "departed", "on_sea", "arrived", "delivered"]);
    expect(m.nodes.find((n) => n.id === "received_bl")?.state).toBe("current");
    expect(m.nodes.find((n) => n.id === "departed")?.state).toBe("upcoming");
  });

  it("row 2: on_sea / atd NOT NULL / direct → departed completed, on_sea current", () => {
    const m = statusToMilestone("on_sea", false, "direct");
    expect(m.current.id).toBe("on_sea");
    expect(m.nodes.map((n) => n.id)).toEqual(["received_bl", "departed", "on_sea", "arrived", "delivered"]);
    expect(m.nodes.find((n) => n.id === "received_bl")?.state).toBe("completed");
    expect(m.nodes.find((n) => n.id === "departed")?.state).toBe("completed");
    expect(m.nodes.find((n) => n.id === "on_sea")?.state).toBe("current");
  });

  it("row 3: on_sea / atd NOT NULL / transit → extra [Transit] node present", () => {
    const m = statusToMilestone("on_sea", false, "transit");
    expect(m.current.id).toBe("on_sea");
    expect(m.nodes.map((n) => n.id)).toEqual(["received_bl", "departed", "on_sea", "transit", "arrived", "delivered"]);
    expect(m.nodes.find((n) => n.id === "transit")?.state).toBe("upcoming");
  });

  it("row 4: arrived / atd NOT NULL / any → [Cập cảng đích ETA] current, prior completed", () => {
    const m = statusToMilestone("arrived", false, "direct");
    expect(m.current.id).toBe("arrived");
    expect(m.nodes.find((n) => n.id === "departed")?.state).toBe("completed");
    expect(m.nodes.find((n) => n.id === "on_sea")?.state).toBe("completed");
    expect(m.nodes.find((n) => n.id === "arrived")?.state).toBe("current");
    expect(m.nodes.find((n) => n.id === "delivered")?.state).toBe("upcoming");
  });

  it("row 5: delivered / atd NOT NULL / any → [Giao hàng] current, all prior completed", () => {
    // IC§1.2 row 5 is shipment_type-agnostic ("any") and specifies only the
    // [Giao hàng] milestone — the [Transit] node is a property of the on_sea
    // row (tied to is_active_leg), NOT of the delivered row. So we assert every
    // node that IS present before `delivered` is completed, without demanding a
    // transit node (the app, matching IC§1.2, drops it once status != on_sea).
    for (const type of ["direct", "transit"] as const) {
      const m = statusToMilestone("delivered", false, type);
      expect(m.current.id).toBe("delivered");
      const deliveredIndex = m.nodes.findIndex((n) => n.id === "delivered");
      m.nodes.slice(0, deliveredIndex).forEach((n) => {
        expect(n.state, `${type}: ${n.id} before delivered must be completed`).toBe("completed");
      });
      expect(m.nodes.find((n) => n.id === "delivered")?.state).toBe("current");
    }
  });
});
