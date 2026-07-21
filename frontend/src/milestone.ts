export type ShipmentStatus = "new" | "on_sea" | "arrived" | "delivered";
export type ShipmentType = "direct" | "transit";
export type MilestoneId = "received_bl" | "departed" | "on_sea" | "transit" | "arrived" | "delivered";
export type MilestoneState = "completed" | "current" | "upcoming";

export interface MilestoneNode {
  id: MilestoneId;
  label: string;
  state: MilestoneState;
}

export interface MilestoneProgress {
  current: MilestoneNode;
  nodes: MilestoneNode[];
}

const labels: Record<MilestoneId, string> = {
  received_bl: "Nhận B/L",
  departed: "Tàu khởi hành ATD",
  on_sea: "Đang trên biển",
  transit: "Transit",
  arrived: "Cập cảng đích ETA",
  delivered: "Giao hàng",
};

export function statusToMilestone(
  status: ShipmentStatus,
  atdIsNull: boolean,
  shipmentType: ShipmentType,
): MilestoneProgress {
  const ids: MilestoneId[] = ["received_bl", "departed", "on_sea"];
  if (status === "on_sea" && shipmentType === "transit") {
    ids.push("transit");
  }
  ids.push("arrived", "delivered");

  const currentId: MilestoneId = status === "new" ? "received_bl" : status;
  const currentIndex = ids.indexOf(currentId);
  const nodes = ids.map<MilestoneNode>((id, index) => ({
    id,
    label: labels[id],
    state: index < currentIndex && !(id === "departed" && atdIsNull) ? "completed" : index === currentIndex ? "current" : "upcoming",
  }));

  return {
    current: nodes[currentIndex],
    nodes,
  };
}
