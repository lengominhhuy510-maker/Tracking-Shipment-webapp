import { describe, expect, it } from "vitest";

import { statusToMilestone } from "./milestone";

describe("statusToMilestone", () => {
  it.each([
    {
      name: "new shipment before departure",
      status: "new" as const,
      atdIsNull: true,
      shipmentType: "direct" as const,
      current: "received_bl",
      nodes: ["received_bl", "departed", "on_sea", "arrived", "delivered"],
    },
    {
      name: "direct shipment at sea",
      status: "on_sea" as const,
      atdIsNull: false,
      shipmentType: "direct" as const,
      current: "on_sea",
      nodes: ["received_bl", "departed", "on_sea", "arrived", "delivered"],
    },
    {
      name: "transit shipment at sea",
      status: "on_sea" as const,
      atdIsNull: false,
      shipmentType: "transit" as const,
      current: "transit",
      nodes: ["received_bl", "departed", "on_sea", "transit", "arrived", "delivered"],
    },
    {
      name: "shipment arrived",
      status: "arrived" as const,
      atdIsNull: false,
      shipmentType: "direct" as const,
      current: "arrived",
      nodes: ["received_bl", "departed", "on_sea", "arrived", "delivered"],
    },
    {
      name: "shipment delivered",
      status: "delivered" as const,
      atdIsNull: false,
      shipmentType: "transit" as const,
      current: "delivered",
      nodes: ["received_bl", "departed", "on_sea", "arrived", "delivered"],
    },
  ])("maps the IC 1.2 row for $name", ({ status, atdIsNull, shipmentType, current, nodes }) => {
    const result = statusToMilestone(status, atdIsNull, shipmentType);

    expect(result.current.id).toBe(current);
    expect(result.nodes.map((node) => node.id)).toEqual(nodes);
    expect(result.nodes.find((node) => node.id === current)?.state).toBe("current");
  });
});
