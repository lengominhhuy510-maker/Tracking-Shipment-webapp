import { useCallback, useEffect, useState } from "react";
import {
  approveProposal,
  getProposals,
  rejectProposal,
  type Proposal,
} from "../api/client";
import { formatLocal } from "./EtaBadge";

interface ProposalsPanelProps {
  onDecided?: () => void;
}

const actionLabels: Record<string, string> = {
  eta_update: "Cập nhật ETA",
  rollover: "Rollover tàu",
};

export default function ProposalsPanel({ onDecided }: ProposalsPanelProps) {
  const [proposals, setProposals] = useState<Proposal[] | null>(null);
  const [busyId, setBusyId] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);

  const refetch = useCallback(async () => {
    try {
      const list = await getProposals("pending");
      setProposals(list);
      setError(null);
    } catch (err) {
      console.warn("Failed to load proposals", err);
      setError("Không tải được danh sách đề xuất.");
    }
  }, []);

  useEffect(() => {
    void refetch();
  }, [refetch]);

  const decide = useCallback(
    async (id: number, action: "approve" | "reject") => {
      setBusyId(id);
      try {
        if (action === "approve") {
          await approveProposal(id);
        } else {
          await rejectProposal(id);
        }
        await refetch();
        onDecided?.();
      } catch (err) {
        console.warn(`Failed to ${action} proposal #${id}`, err);
        setError(`Không ${action === "approve" ? "duyệt" : "từ chối"} được đề xuất #${id}.`);
      } finally {
        setBusyId(null);
      }
    },
    [refetch, onDecided],
  );

  return (
    <section className="proposals-panel">
      <header className="shipment-list-header">
        <h2>Đề xuất từ Agent</h2>
        <button type="button" className="btn-back" onClick={() => void refetch()}>Làm mới</button>
      </header>
      {error && <p className="form-error">{error}</p>}
      {proposals === null && !error && <p className="list-loading">Đang tải…</p>}
      {proposals !== null && proposals.length === 0 && (
        <p className="list-empty">Không có đề xuất nào đang chờ duyệt.</p>
      )}
      {proposals !== null &&
        proposals.map((proposal) => {
          const extracted = proposal.extracted_json ?? {};
          const containers = Array.isArray(extracted.containers) ? extracted.containers : [];
          return (
            <article key={proposal.id} className="proposal-card">
              <div className="proposal-card-head">
                <span className="shipment-title">
                  Đề xuất #{proposal.id}
                  {proposal.shipment_id !== null && <> — Lô #{proposal.shipment_id}</>}
                </span>
                <span className="status-badge proposal-pending">Chờ duyệt</span>
              </div>
              <dl className="shipment-facts">
                <div>
                  <dt>Hành động đề xuất</dt>
                  <dd>{proposal.proposed_action ? (actionLabels[proposal.proposed_action] ?? proposal.proposed_action) : "—"}</dd>
                </div>
                {extracted.new_eta != null && (
                  <div>
                    <dt>ETA mới</dt>
                    <dd>{formatLocal(String(extracted.new_eta))}</dd>
                  </div>
                )}
                {extracted.reason != null && (
                  <div>
                    <dt>Lý do</dt>
                    <dd>{String(extracted.reason)}</dd>
                  </div>
                )}
                {containers.length > 0 && (
                  <div>
                    <dt>Containers</dt>
                    <dd>{containers.join(", ")}</dd>
                  </div>
                )}
                <div>
                  <dt>Tạo lúc</dt>
                  <dd>{formatLocal(proposal.created_at)}</dd>
                </div>
              </dl>
              <div className="proposal-actions">
                <button
                  type="button"
                  className="btn-approve"
                  disabled={busyId === proposal.id}
                  onClick={() => void decide(proposal.id, "approve")}
                >
                  {busyId === proposal.id ? "Đang xử lý…" : "Duyệt"}
                </button>
                <button
                  type="button"
                  className="btn-reject"
                  disabled={busyId === proposal.id}
                  onClick={() => void decide(proposal.id, "reject")}
                >
                  Từ chối
                </button>
              </div>
            </article>
          );
        })}
    </section>
  );
}
