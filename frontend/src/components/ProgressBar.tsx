import type { MilestoneProgress } from "../milestone";

interface ProgressBarProps {
  progress: MilestoneProgress;
}

export default function ProgressBar({ progress }: ProgressBarProps) {
  return (
    <div className="progress-bar">
      {progress.nodes.map((node, index) => (
        <div key={node.id} className={`milestone-node ${node.state}`}>
          {index > 0 && <span className="milestone-connector" aria-hidden="true" />}
          <span className={node.state === "current" ? "milestone-dot pulse" : "milestone-dot"} />
          <span className="milestone-label">{node.label}</span>
        </div>
      ))}
    </div>
  );
}
