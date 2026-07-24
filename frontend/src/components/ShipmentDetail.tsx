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

interface TideExtreme {
  time: string;
  height: number;
  type: string;
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

      <section className="env-conditions">
        <h3>Điều kiện biển</h3>
        {(() => {
          const env = shipment.env;
          const hasWeather = env && env.weather_fetched_at !== null;
          const hasTide = env && env.tide_fetched_at !== null && (env.tide_extremes?.length ?? 0) > 0;
          if (!hasWeather && !hasTide) {
            return <p>Chưa có dữ liệu sóng / gió / thủy triều.</p>;
          }
          return (
            <>
              <dl className="shipment-facts">
                <div>
                  <dt>Gió</dt>
                  <dd>{env!.wind_speed_kn === null ? "—" : `${env!.wind_speed_kn.toFixed(1)} kn`}</dd>
                </div>
                <div>
                  <dt>Sóng</dt>
                  <dd>{env!.wave_height_m === null ? "—" : `${env!.wave_height_m.toFixed(1)} m`}</dd>
                </div>
                <div>
                  <dt>Dòng chảy</dt>
                  <dd>
                    {env!.current_speed_kn === null
                      ? "—"
                      : `${env!.current_speed_kn.toFixed(1)} kn${env!.current_direction_deg === null ? "" : ` @ ${Math.round(env!.current_direction_deg)}°`}`}
                  </dd>
                </div>
                <div>
                  <dt>Cập nhật thời tiết</dt>
                  <dd>{formatLocal(env!.weather_fetched_at)}</dd>
                </div>
                {hasTide && (
                  <>
                    <div>
                      <dt>Trạm thủy triều</dt>
                      <dd>
                        {env!.tide_station_name ?? "—"}
                        {env!.tide_station_distance_km === null
                          ? ""
                          : ` (${env!.tide_station_distance_km.toFixed(0)} km)`}
                      </dd>
                    </div>
                    <div>
                      <dt>Cập nhật thủy triều</dt>
                      <dd>{formatLocal(env!.tide_fetched_at)}</dd>
                    </div>
                  </>
                )}
              </dl>
              {hasTide && (
                <table className="tide-extremes">
                  <thead>
                    <tr>
                      <th>Con nước</th>
                      <th>Thời điểm</th>
                      <th>Mực (m)</th>
                    </tr>
                  </thead>
                  <tbody>
                    {(env!.tide_extremes as TideExtreme[]).map((extreme, idx) => (
                      <tr key={idx}>
                        <td>{extreme.type === "high" ? "Triều cường" : extreme.type === "low" ? "Triều kiệt" : extreme.type}</td>
                        <td>{formatLocal(extreme.time)}</td>
                        <td>{typeof extreme.height === "number" ? extreme.height.toFixed(2) : "—"}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </>
          );
        })()}
      </section>

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
