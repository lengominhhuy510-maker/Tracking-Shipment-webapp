import { useCallback, useEffect, useRef, useState } from "react";
import { getShipment, getShipments, type ShipmentDetail as ShipmentDetailData, type ShipmentListItem } from "./api/client";
import { createShipmentRealtime, type DeviationAlertState } from "./api/ws";
import ShipmentList from "./components/ShipmentList";
import ShipmentDetail from "./components/ShipmentDetail";
import CreateShipmentForm from "./components/CreateShipmentForm";
import Login, { type AuthUser } from "./components/Login";
import ProposalsPanel from "./components/ProposalsPanel";

const APP_STYLES = `
  body { margin: 0; font-family: "Segoe UI", system-ui, sans-serif; background: #f4f6f8; color: #1f2937; }
  .app-shell { max-width: 960px; margin: 0 auto; padding: 16px; }
  .app-title { display: flex; align-items: baseline; justify-content: space-between; }
  .shipment-list-header { display: flex; justify-content: space-between; align-items: center; }
  .btn-create, .btn-back, .form-actions button { padding: 6px 14px; border-radius: 6px; border: 1px solid #d1d5db; background: #fff; cursor: pointer; }
  .btn-create { background: #1d4ed8; color: #fff; border-color: #1d4ed8; }
  .shipment-row { display: flex; justify-content: space-between; gap: 12px; background: #fff; border: 1px solid #e5e7eb; border-radius: 8px; padding: 12px 16px; margin-bottom: 10px; cursor: pointer; }
  .shipment-row:hover { border-color: #1d4ed8; }
  .shipment-row-main { display: flex; flex-direction: column; gap: 4px; }
  .shipment-title { font-weight: 600; }
  .shipment-sub { font-size: 13px; color: #6b7280; }
  .shipment-row-meta { display: flex; flex-direction: column; align-items: flex-end; gap: 4px; font-size: 13px; }
  .status-badge { padding: 2px 8px; border-radius: 999px; background: #e5e7eb; }
  .status-on_sea { background: #dbeafe; color: #1d4ed8; }
  .status-arrived { background: #dcfce7; color: #15803d; }
  .status-delivered { background: #f3e8ff; color: #7e22ce; }
  .monitoring-badge { font-size: 12px; }
  .eta-badge { display: inline-block; padding: 4px 10px; border-radius: 6px; background: #dbeafe; color: #1d4ed8; font-weight: 600; }
  .eta-badge-deviation { background: #fee2e2; color: #b91c1c; }
  .progress-bar { display: flex; align-items: flex-start; margin: 20px 0; }
  .milestone-node { display: flex; flex: 1; flex-direction: column; align-items: center; position: relative; text-align: center; }
  .milestone-connector { position: absolute; top: 7px; right: 50%; width: 100%; height: 2px; background: #d1d5db; z-index: 0; }
  .milestone-node.completed .milestone-connector, .milestone-node.current .milestone-connector { background: #1d4ed8; }
  .milestone-dot { width: 16px; height: 16px; border-radius: 50%; background: #d1d5db; z-index: 1; }
  .milestone-node.completed .milestone-dot { background: #1d4ed8; }
  .milestone-node.current .milestone-dot { background: #1d4ed8; box-shadow: 0 0 0 4px rgba(29, 78, 216, 0.25); }
  .milestone-dot.pulse { animation: milestone-pulse 1.2s ease-in-out infinite; }
  @keyframes milestone-pulse { 0%, 100% { box-shadow: 0 0 0 3px rgba(29, 78, 216, 0.35); } 50% { box-shadow: 0 0 0 8px rgba(29, 78, 216, 0.1); } }
  .milestone-label { font-size: 12px; margin-top: 6px; color: #374151; }
  .shipment-detail-header { display: flex; align-items: center; gap: 12px; flex-wrap: wrap; }
  .shipment-facts { display: grid; grid-template-columns: repeat(auto-fill, minmax(220px, 1fr)); gap: 8px; background: #fff; border: 1px solid #e5e7eb; border-radius: 8px; padding: 12px 16px; }
  .shipment-facts dt { font-size: 12px; color: #6b7280; }
  .shipment-facts dd { margin: 0; font-weight: 600; }
  .onboarding-error { color: #b91c1c; }
  .vessel-map { margin: 16px 0; border-radius: 8px; overflow: hidden; border: 1px solid #e5e7eb; }
  .vessel-map-empty { padding: 40px; text-align: center; color: #6b7280; background: #fff; }
  .eta-history table { width: 100%; border-collapse: collapse; background: #fff; }
  .eta-history th, .eta-history td { padding: 8px 10px; border-bottom: 1px solid #e5e7eb; text-align: left; font-size: 13px; }
  .env-conditions { margin: 16px 0; }
  .tide-extremes { width: 100%; border-collapse: collapse; background: #fff; margin-top: 8px; }
  .tide-extremes th, .tide-extremes td { padding: 8px 10px; border-bottom: 1px solid #e5e7eb; text-align: left; font-size: 13px; }
  .create-shipment-form { display: flex; flex-direction: column; gap: 10px; background: #fff; border: 1px solid #e5e7eb; border-radius: 8px; padding: 16px; max-width: 480px; }
  .create-shipment-form label { display: flex; flex-direction: column; gap: 4px; font-size: 13px; }
  .create-shipment-form input, .create-shipment-form select { padding: 6px 8px; border: 1px solid #d1d5db; border-radius: 6px; font-size: 14px; }
  .form-error { color: #b91c1c; }
  .form-actions { display: flex; gap: 8px; }
  .form-actions button[type="submit"] { background: #1d4ed8; color: #fff; border-color: #1d4ed8; }
  .alert-banner { background: #fef3c7; border: 1px solid #f59e0b; border-radius: 6px; padding: 8px 12px; margin-bottom: 12px; font-size: 13px; }
  .login-screen { background: #fff; border: 1px solid #e5e7eb; border-radius: 8px; padding: 32px; max-width: 420px; margin: 60px auto; text-align: center; }
  .login-buttons { display: flex; flex-direction: column; gap: 10px; margin-top: 16px; }
  .btn-login { display: block; padding: 10px 16px; border-radius: 6px; border: 1px solid #d1d5db; background: #fff; color: #1f2937; text-decoration: none; font-weight: 600; }
  .btn-login:hover { border-color: #1d4ed8; color: #1d4ed8; }
  .user-chip { font-size: 13px; color: #6b7280; display: flex; align-items: center; gap: 8px; }
  .btn-logout { padding: 4px 10px; border-radius: 6px; border: 1px solid #d1d5db; background: #fff; cursor: pointer; font-size: 12px; }
  .view-tabs { display: flex; gap: 8px; margin-bottom: 12px; }
  .view-tab { padding: 6px 14px; border-radius: 6px; border: 1px solid #d1d5db; background: #fff; cursor: pointer; }
  .view-tab.active { background: #1d4ed8; color: #fff; border-color: #1d4ed8; }
  .proposal-card { background: #fff; border: 1px solid #e5e7eb; border-radius: 8px; padding: 12px 16px; margin-bottom: 10px; display: flex; flex-direction: column; gap: 10px; }
  .proposal-card-head { display: flex; justify-content: space-between; align-items: center; }
  .status-badge.proposal-pending { background: #fef3c7; color: #b45309; }
  .proposal-actions { display: flex; gap: 8px; }
  .btn-approve { padding: 6px 14px; border-radius: 6px; border: 1px solid #15803d; background: #15803d; color: #fff; cursor: pointer; }
  .btn-reject { padding: 6px 14px; border-radius: 6px; border: 1px solid #b91c1c; background: #fff; color: #b91c1c; cursor: pointer; }
  .btn-approve:disabled, .btn-reject:disabled { opacity: 0.6; cursor: default; }
`;

type View = "list" | "detail" | "create" | "proposals";
type AuthState =
  | { status: "loading" }
  | { status: "anonymous" }
  | { status: "authenticated"; user: AuthUser };

export default function App() {
  const [auth, setAuth] = useState<AuthState>({ status: "loading" });
  const [shipments, setShipments] = useState<ShipmentListItem[] | null>(null);
  const [openShipment, setOpenShipment] = useState<ShipmentDetailData | null>(null);
  const [view, setView] = useState<View>("list");
  const [deviationAlert, setDeviationAlert] = useState<DeviationAlertState | null>(null);
  const [banner, setBanner] = useState<string | null>(null);

  const shipmentsRef = useRef<ShipmentListItem[] | null>(null);
  const openShipmentRef = useRef<ShipmentDetailData | null>(null);
  shipmentsRef.current = shipments;
  openShipmentRef.current = openShipment;

  const refetchShipments = useCallback(async () => {
    const list = await getShipments();
    shipmentsRef.current = list;
    setShipments(list);
  }, []);

  const refetchOpenShipment = useCallback(async () => {
    const openId = openShipmentRef.current?.id;
    if (openId === undefined) return;
    const detail = await getShipment(openId);
    openShipmentRef.current = detail;
    setOpenShipment(detail);
  }, []);

  useEffect(() => {
    let cancelled = false;
    fetch("/auth/me", { credentials: "same-origin" })
      .then(async (response) => {
        if (cancelled) return;
        if (response.ok) {
          const user = (await response.json()) as AuthUser;
          setAuth({ status: "authenticated", user });
        } else {
          setAuth({ status: "anonymous" });
        }
      })
      .catch(() => {
        if (!cancelled) setAuth({ status: "anonymous" });
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const isAuthenticated = auth.status === "authenticated";

  useEffect(() => {
    if (!isAuthenticated) return;
    const controller = createShipmentRealtime({
      getShipments: () => shipmentsRef.current,
      setShipments: (next) => {
        shipmentsRef.current = next;
        setShipments(next);
      },
      getOpenShipment: () => openShipmentRef.current,
      setOpenShipment: (next) => {
        openShipmentRef.current = next;
        setOpenShipment(next);
      },
      refetchShipments,
      refetchOpenShipment,
      setDeviationAlert,
      onTidalAlert: (alert) => setBanner(alert.message),
      onStatusChangeSuggested: (event) => {
        setBanner(`Lô #${event.shipment_id}: đề xuất chuyển trạng thái "${event.data.suggested}" — ${event.data.reason}`);
      },
    });
    controller.connect();
    return () => {
      controller.close();
    };
  }, [isAuthenticated, refetchShipments, refetchOpenShipment]);

  useEffect(() => {
    if (!isAuthenticated) return;
    refetchShipments().catch((error: unknown) => {
      console.warn("Initial shipment fetch failed", error);
    });
  }, [isAuthenticated, refetchShipments]);

  const openDetail = useCallback(async (id: number) => {
    try {
      const detail = await getShipment(id);
      openShipmentRef.current = detail;
      setOpenShipment(detail);
      setView("detail");
    } catch (error) {
      console.warn("Failed to load shipment detail", error);
      setBanner(`Không tải được chi tiết lô #${id}.`);
    }
  }, []);

  const backToList = useCallback(() => {
    openShipmentRef.current = null;
    setOpenShipment(null);
    setView("list");
  }, []);

  if (auth.status === "loading") {
    return (
      <div className="app-shell">
        <style>{APP_STYLES}</style>
        <p>Đang kiểm tra phiên đăng nhập…</p>
      </div>
    );
  }

  if (auth.status === "anonymous") {
    return (
      <div className="app-shell">
        <style>{APP_STYLES}</style>
        <header className="app-title">
          <h1>Shipment Monitor</h1>
        </header>
        <Login />
      </div>
    );
  }

  return (
    <div className="app-shell">
      <style>{APP_STYLES}</style>
      <header className="app-title">
        <h1>Shipment Monitor</h1>
        <span className="user-chip">
          {auth.user.name ?? auth.user.email} ({auth.user.role})
          <a className="btn-logout" href="#" onClick={(event) => {
            event.preventDefault();
            fetch("/auth/logout", { method: "POST", credentials: "same-origin" })
              .finally(() => setAuth({ status: "anonymous" }));
          }}>Đăng xuất</a>
        </span>
      </header>
      {banner && (
        <div className="alert-banner" role="status">
          {banner}
          <button type="button" onClick={() => setBanner(null)} style={{ marginLeft: 8 }}>Đóng</button>
        </div>
      )}
      {(view === "list" || view === "proposals") && (
        <nav className="view-tabs">
          <button type="button" className={view === "list" ? "view-tab active" : "view-tab"} onClick={() => setView("list")}>Lô hàng</button>
          <button type="button" className={view === "proposals" ? "view-tab active" : "view-tab"} onClick={() => setView("proposals")}>Đề xuất Agent</button>
        </nav>
      )}
      {view === "list" && (
        <ShipmentList
          shipments={shipments}
          onOpen={(id) => void openDetail(id)}
          onCreate={() => setView("create")}
        />
      )}
      {view === "create" && (
        <CreateShipmentForm
          onCreated={(created) => {
            openShipmentRef.current = created;
            setOpenShipment(created);
            setView("detail");
            void refetchShipments().catch((error: unknown) => {
              console.warn("List refetch after create failed", error);
            });
          }}
          onCancel={() => setView("list")}
        />
      )}
      {view === "proposals" && (
        <ProposalsPanel
          onDecided={() => {
            void refetchShipments().catch((error: unknown) => {
              console.warn("List refetch after proposal decision failed", error);
            });
          }}
        />
      )}
      {view === "detail" && openShipment && (
        <ShipmentDetail shipment={openShipment} deviationAlert={deviationAlert} onBack={backToList} />
      )}
    </div>
  );
}
