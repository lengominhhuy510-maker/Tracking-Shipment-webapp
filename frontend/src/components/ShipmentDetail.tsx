import type { ShipmentDetail as ShipmentDetailData } from "../api/client";
import type { DeviationAlertState } from "../api/ws";
import { statusToMilestone } from "../milestone";
import ProgressBar from "./ProgressBar";
import VesselMap from "./VesselMap";
import EtaBadge, { formatLocal } from "./EtaBadge";

interface ShipmentDetailProps {
  shipment: ShipmentDetailData;
  deviationAlert: DeviationAlertState | null;
  onBack: () => void;
}

export default function ShipmentDetail({ shipment, deviationAlert, onBack }: ShipmentDetailProps) {
  const progress = statusToMilestone(shipment.status, shipment.atd === null, shipment.shipment_type);

  return (
    <section className="shipment-detail">
      <header className="shipment-detail-header">
        <button type="button" className="btn-back" onClick={onBack}>← Danh sách</button>
        <h2>Lô #{shipment.id} — {shipment.bl_number}</h2>
        <EtaBadge etaCurrent={shipment.eta_current} deviationAlert={deviationAlert} shipmentId={shipment.id} />
      </header>

      <dl className="shipment-facts">
        <div><dt>Container</dt><dd>{shipment.container_no}</dd></div>
        <div><dt>Tàu / chuyến</dt><dd>{shipment.vessel_name}{shipment.voyage_no ? ` / ${shipment.voyage_no}` : ""}</dd></div>
        <div><dt>Hãng tàu</dt><dd>{shipment.carrier}</dd></div>
        <div><dt>Tuyến</dt><dd>{shipment.pol} → {shipment.pod}</dd></div>
        <div><dt>Incoterm</dt><dd>{shipment.incoterm}</dd></div>
        <div><dt>ATD</dt><dd>{formatLocal(shipment.atd)}</dd></div>
        <div><dt>ETA gốc</dt><dd>{formatLocal(shipment.eta_original)}</dd></div>
        {shipment.onboarding_error && (
          <div><dt>Lỗi onboarding</dt><dd className="onboarding-error">{shipment.onboarding_error}</dd></div>
        )}
      </dl>

      <ProgressBar progress={progress} />

      <VesselMap
        shipmentId={shipment.id}
        lat={shipment.current_lat}
        lon={shipment.current_lon}
        sog={shipment.current_sog}
        cog={shipment.current_cog}
        vesselName={shipment.vessel_name}
      />

      <section className="eta-history">
        <h3>Lịch sử ETA</h3>
        {shipment.recent_eta_history.length === 0 && <p>Chưa có lịch sử ETA.</p>}
        {shipment.recent_eta_history.length > 0 && (
          <table>
            <thead>
              <tr>
                <th>Thời điểm ghi</th>
                <th>ETA</th>
                <th>Nguồn</th>
                <th>Lệch (%)</th>
              </tr>
            </thead>
            <tbody>
              {shipment.recent_eta_history.map((entry) => (
                <tr key={entry.id}>
                  <td>{formatLocal(entry.recorded_at)}</td>
                  <td>{formatLocal(entry.eta_value)}</td>
                  <td>{entry.source}</td>
                  <td>{entry.deviation_pct === null ? "—" : `${entry.deviation_pct.toFixed(1)}%`}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>
    </section>
  );
}
