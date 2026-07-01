import { useMemo, useState } from "react";
import type { InterAgentApprovalRecord, InterAgentRunDetail } from "../api/client";

type InterAgentRunPanelProps = {
  approvalsByRunId: Record<string, InterAgentApprovalRecord[]>;
  onResolveApproval: (approvalId: string, approved: boolean) => Promise<void>;
  runs: InterAgentRunDetail[];
};

export function InterAgentRunPanel({
  approvalsByRunId,
  onResolveApproval,
  runs,
}: InterAgentRunPanelProps) {
  const [resolvingApprovalId, setResolvingApprovalId] = useState<string | null>(null);
  const pendingApprovals = useMemo(
    () =>
      runs.flatMap((detail) =>
        (approvalsByRunId[detail.run.run_id] || []).filter((approval) => approval.status === "pending"),
      ),
    [approvalsByRunId, runs],
  );

  if (pendingApprovals.length === 0) {
    return null;
  }

  async function resolveApproval(approvalId: string, approved: boolean) {
    setResolvingApprovalId(approvalId);
    try {
      await onResolveApproval(approvalId, approved);
    } finally {
      setResolvingApprovalId(null);
    }
  }

  return (
    <div className="chatapp-inter-agent-panel">
      <div className="chatapp-inter-agent-approvals" aria-live="polite">
        {pendingApprovals.map((approval) => (
          <article className="chatapp-inter-agent-approval" key={approval.approval_id}>
            <div className="chatapp-inter-agent-approval__main">
              <span className={`chatapp-inter-agent-approval__risk is-${approval.risk_level}`}>{approval.risk_level}</span>
              <div className="chatapp-inter-agent-approval__copy">
                <strong>{approval.operation_kind}</strong>
                <p>{approval.summary}</p>
              </div>
            </div>
            <div className="chatapp-inter-agent-approval__actions">
              <button
                className="chatapp-inter-agent-approval__button"
                disabled={resolvingApprovalId === approval.approval_id}
                onClick={() => resolveApproval(approval.approval_id, false)}
                type="button"
              >
                Reject
              </button>
              <button
                className="chatapp-inter-agent-approval__button is-primary"
                disabled={resolvingApprovalId === approval.approval_id}
                onClick={() => resolveApproval(approval.approval_id, true)}
                type="button"
              >
                Approve
              </button>
            </div>
          </article>
        ))}
      </div>
    </div>
  );
}
