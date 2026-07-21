import dayjs from "dayjs";
import type { DeviationAlertState } from "../api/ws";

interface EtaBadgeProps {
  etaCurrent: string | null;
  deviationAlert: DeviationAlertState | null;
  shipmentId: number;
}

export function formatLocal(value: string | null): string {
  return value ? dayjs(value).format("DD/MM/YYYY HH:mm") : "—";
}

export default function EtaBadge({ etaCurrent, deviationAlert, shipmentId }: EtaBadgeProps) {
  const hasDeviation = deviationAlert?.shipmentId === shipmentId;
  return (
    <span className={hasDeviation ? "eta-badge eta-badge-deviation" : "eta-badge"} title={hasDeviation ? `Lệch ${deviationAlert.deviationPct.toFixed(1)}% (ngưỡng ${deviationAlert.threshold}%)` : undefined}>
      ETA: {formatLocal(etaCurrent)}
      {hasDeviation && <span className="eta-deviation-pct"> ⚠ {deviationAlert.deviationPct > 0 ? "+" : ""}{deviationAlert.deviationPct.toFixed(1)}%</span>}
    </span>
  );
}
