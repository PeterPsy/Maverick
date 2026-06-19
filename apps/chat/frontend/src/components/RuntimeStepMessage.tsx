import type { RuntimeStepMessage as RuntimeStep } from "../api/client";

export function RuntimeStepMessage({
  onOpenInterAgentGraph,
  step,
}: {
  onOpenInterAgentGraph?: (runId: string) => void;
  step: RuntimeStep;
}) {
  const interAgentRunId = interAgentRunIdFromStep(step);
  const isLive = !isTerminalInterAgentStep(step);
  if (interAgentRunId) {
    return (
      <div className="chatapp-inter-agent-message">
        <div className="chatapp-inter-agent-message__meta">
          <span className="chatapp-inter-agent-message__icon material-symbols-rounded" aria-hidden="true">
            hub
          </span>
          <div className="chatapp-inter-agent-message__meta-top">
            <span>Orchestrator</span>
            <span>{summaryKindLabel(step.detail.summary_kind)}</span>
          </div>
          {onOpenInterAgentGraph ? (
            <button
              className={`chatapp-inter-agent-message__graph ${isLive ? "is-live" : ""}`}
              onClick={() => onOpenInterAgentGraph(interAgentRunId)}
              type="button"
            >
              Agent nodes
            </button>
          ) : null}
        </div>
        <p>{step.label}</p>
      </div>
    );
  }
  return (
    <div className="chatapp-agent-step chatapp-agent-step--thought">
      <div className="chatapp-agent-step__body">
        <p>{step.label}</p>
      </div>
    </div>
  );
}

function interAgentRunIdFromStep(step: RuntimeStep): string {
  if (step.detail.step_kind !== "inter_agent_summary") {
    return "";
  }
  return typeof step.detail.inter_agent_run_id === "string" ? step.detail.inter_agent_run_id : "";
}

function isTerminalInterAgentStep(step: RuntimeStep): boolean {
  const candidates = [step.detail.summary_kind, step.detail.run_status, step.detail.status];
  return candidates.some((value) => typeof value === "string" && ["completed", "failed", "cancelled"].includes(value));
}

function summaryKindLabel(value: unknown): string {
  if (typeof value !== "string" || !value.trim()) {
    return "Update";
  }
  return value.slice(0, 1).toUpperCase() + value.slice(1).replace(/_/g, " ");
}
