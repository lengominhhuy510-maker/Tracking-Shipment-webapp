import type { ShipmentListItem } from "../api/client";
import { formatLocal } from "./EtaBadge";

interface ShipmentListProps {
  shipments: ShipmentListItem[] | null;
  onOpen: (id: number) => void;
  onCreate: () => void;
}

const statusLabels: Record<ShipmentListItem["status"], string> = {
  new: "Mới",
  on_sea: "Đang trên biển",
  arrived: "Đã cập cảng",
  delivered: "Đã giao",
};

export default function ShipmentList({ shipments, onOpen, onCreate }: ShipmentListProps) {
  return (
    <section className="shipment-list">
      <header className="shipment-list-header">
        <h2>Danh sách lô hàng</h2>
        <button type="button" className="btn-create" onClick={onCreate}>Tạo lô</button>
      </header>
      {shipments === null && <p className="list-loading">Đang tải…</p>}
      {shipments !== null && shipments.length === 0 && <p className="list-empty">Chưa có lô hàng nào.</p>}
      {shipments !== null && shipments.map((shipment) => (
        <article
          key={shipment.id}
          className="shipment-row"
          onClick={() => onOpen(shipment.id)}
          onKeyDown={(event) => {
            if (event.key === "Enter") onOpen(shipment.id);
          }}
          role="button"
          tabIndex={0}
        >
          <div className="shipment-row-main">
            <span className="shipment-title">Lô #{shipment.id} — {shipment.bl_number}</span>
            <span className="shipment-sub">
              {shipment.container_no} · {shipment.vessel_name}
              {shipment.voyage_no ? ` / ${shipment.voyage_no}` : ""} · {shipment.pol} → {shipment.pod}
            </span>
          </div>
          <div className="shipment-row-meta">
            <span className={`status-badge status-${shipment.status}`}>{statusLabels[shipment.status]}</span>
            <span
              className={shipment.monitoring_mode === "auto_email" ? "monitoring-badge monitoring-auto" : "monitoring-badge monitoring-manual"}
              title={shipment.monitoring_mode === "auto_email" ? "Theo dõi tự động qua email" : "Theo dõi thủ công"}
            >
              {shipment.monitoring_mode === "auto_email" ? "🟢 Auto" : "⚪ Manual"}
            </span>
            <span className="shipment-eta">ETA: {formatLocal(shipment.eta_current)}</span>
          </div>
        </article>
      ))}
    </section>
  );
}
