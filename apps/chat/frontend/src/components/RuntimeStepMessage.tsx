import type { RuntimeStepMessage as RuntimeStep } from "../api/client";

const FINAL_INTER_AGENT_SUMMARY_KINDS = new Set(["completed", "failed", "cancelled"]);

export function RuntimeStepMessage({
  onOpenInterAgentGraph,
  step,
}: {
  onOpenInterAgentGraph?: (runId: string) => void;
  step: RuntimeStep;
}) {
  const boardRunId = interAgentFinalSummaryRunId(step);
  return (
    <div className="chatapp-agent-step chatapp-agent-step--thought">
      <div className="chatapp-agent-step__body">
        <p>{step.label}</p>
        {boardRunId && onOpenInterAgentGraph ? (
          <button
            className="chatapp-agent-step__board"
            onClick={() => onOpenInterAgentGraph(boardRunId)}
            type="button"
          >
            <span aria-hidden="true" className="chatapp-live-board-glow">
              <span className="chatapp-live-board-glow__layer chatapp-live-board-glow__layer--outer" />
              <span className="chatapp-live-board-glow__layer chatapp-live-board-glow__layer--a" />
              <span className="chatapp-live-board-glow__layer chatapp-live-board-glow__layer--b" />
              <span className="chatapp-live-board-glow__layer chatapp-live-board-glow__layer--c" />
              <span className="chatapp-live-board-glow__layer chatapp-live-board-glow__layer--bright" />
              <span className="chatapp-live-board-glow__layer chatapp-live-board-glow__layer--rim" />
            </span>
            <span aria-hidden="true" className="material-symbols-rounded chatapp-agent-step__board-icon">
              account_tree
            </span>
            <span className="chatapp-agent-step__board-label">Open multi-agent board</span>
          </button>
        ) : null}
      </div>
    </div>
  );
}

function interAgentFinalSummaryRunId(step: RuntimeStep): string {
  const detail = step.detail || {};
  const stepKind = typeof detail.step_kind === "string" ? detail.step_kind : "";
  const summaryKind = typeof detail.summary_kind === "string" ? detail.summary_kind : "";
  const runId = typeof detail.inter_agent_run_id === "string" ? detail.inter_agent_run_id.trim() : "";
  if (stepKind !== "inter_agent_summary" || !FINAL_INTER_AGENT_SUMMARY_KINDS.has(summaryKind) || !runId) {
    return "";
  }
  return runId;
}
