import { useMemo, useState } from "react";
import type { InterAgentApprovalRecord, InterAgentEventRecord, InterAgentRunDetail } from "../api/client";

type InterAgentRunPanelProps = {
  approvalsByRunId: Record<string, InterAgentApprovalRecord[]>;
  eventsByRunId: Record<string, InterAgentEventRecord[]>;
  onOpenGraph: (runId: string) => void;
  onResolveApproval: (approvalId: string, approved: boolean) => Promise<void>;
  runs: InterAgentRunDetail[];
};

export function InterAgentRunPanel({
  approvalsByRunId,
  eventsByRunId,
  onOpenGraph,
  onResolveApproval,
  runs,
}: InterAgentRunPanelProps) {
  const [resolvingApprovalId, setResolvingApprovalId] = useState<string | null>(null);
  const latestRun = runs.at(-1) || null;
  const pendingApprovals = useMemo(
    () =>
      runs.flatMap((detail) =>
        (approvalsByRunId[detail.run.run_id] || [])
          .filter((approval) => approval.status === "pending")
          .map((approval) => ({ approval, run: detail })),
      ),
    [approvalsByRunId, runs],
  );

  if (!latestRun && pendingApprovals.length === 0) {
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
      {latestRun ? (
        <InterAgentBanner
          events={eventsByRunId[latestRun.run.run_id] || []}
          onOpenGraph={onOpenGraph}
          runDetail={latestRun}
        />
      ) : null}
      {pendingApprovals.length ? (
        <div className="chatapp-inter-agent-approvals" aria-live="polite">
          {pendingApprovals.map(({ approval, run }) => (
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
                <button
                  aria-label="Open graph"
                  className="chatapp-inter-agent-approval__graph"
                  onClick={() => onOpenGraph(run.run.run_id)}
                  type="button"
                >
                  <span aria-hidden="true" className="material-symbols-rounded">
                    account_tree
                  </span>
                </button>
              </div>
            </article>
          ))}
        </div>
      ) : null}
    </div>
  );
}

function InterAgentBanner({
  events,
  onOpenGraph,
  runDetail,
}: {
  events: InterAgentEventRecord[];
  onOpenGraph: (runId: string) => void;
  runDetail: InterAgentRunDetail;
}) {
  const latestSummary = [...events]
    .reverse()
    .map((event) => textPayload(event.payload.summary) || textPayload(event.payload.status))
    .find(Boolean);
  const participantCount = runDetail.participants.filter((participant) => participant.kind !== "orchestrator").length;
  const budget = runDetail.budget_policy;
  return (
    <aside className={`chatapp-inter-agent-banner is-${runDetail.run.status}`}>
      <div className="chatapp-inter-agent-banner__icon" aria-hidden="true">
        <span className="material-symbols-rounded">hub</span>
      </div>
      <div className="chatapp-inter-agent-banner__body">
        <div className="chatapp-inter-agent-banner__meta">
          <span>{runStatusLabel(runDetail.run.status)}</span>
          <span>{participantLabel(participantCount || 1)}</span>
          {budget ? <span>{budget.max_total_turns} turns</span> : null}
        </div>
        {latestSummary ? <p>{latestSummary}</p> : null}
      </div>
      <button className="chatapp-inter-agent-banner__graph" onClick={() => onOpenGraph(runDetail.run.run_id)} type="button">
        <span aria-hidden="true" className="material-symbols-rounded">
          account_tree
        </span>
        <span>Open graph</span>
      </button>
    </aside>
  );
}

function runStatusLabel(status: string): string {
  if (status === "waiting_approval") {
    return "Waiting approval";
  }
  return status
    .split("_")
    .map((part) => part.slice(0, 1).toUpperCase() + part.slice(1))
    .join(" ");
}

function participantLabel(count: number): string {
  return `${count} participant${count === 1 ? "" : "s"}`;
}

function textPayload(value: unknown): string {
  return typeof value === "string" ? value.trim() : "";
}
