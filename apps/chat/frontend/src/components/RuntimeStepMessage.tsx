import type { RuntimeStepMessage as RuntimeStep } from "../api/client";
import { ActivityDisclosure } from "./ActivityDisclosure";

type RuntimeStepMessageProps = {
  createdAt?: string;
  step: RuntimeStep;
};

type RuntimeStepPresentation = {
  description: string;
  eventType: string;
  eyebrow: string;
  label: string;
  objective: string;
  provider: string;
  status: string;
  timeUsedSeconds?: number;
  title: string;
  tokenBudget?: number;
  tokensUsed?: number;
  inputTokens?: number;
  outputTokens?: number;
  estimatedCostMicrousd?: number;
};

export function RuntimeStepMessage({ createdAt, step }: RuntimeStepMessageProps) {
  if (!isExpandableRuntimeStep(step)) {
    return (
      <div className="chatapp-agent-step chatapp-agent-step--thought">
        <div className="chatapp-agent-step__body">
          <p>{step.label}</p>
        </div>
      </div>
    );
  }

  const presentation = runtimeStepPresentation(step);
  return (
    <ActivityDisclosure createdAt={createdAt} label={presentation.label}>
      <RuntimeStepPanel presentation={presentation} step={step} />
    </ActivityDisclosure>
  );
}

export function isExpandableRuntimeStep(step: RuntimeStep): boolean {
  const eventType = runtimeEventType(step.detail);
  return Boolean(eventType) && (
    isGoalEvent(eventType)
    || normalizeEventType(eventType) === "provider.usage"
    || Boolean(recordValue(step.detail.raw))
  );
}

function RuntimeStepPanel({ presentation, step }: { presentation: RuntimeStepPresentation; step: RuntimeStep }) {
  const hasUsage =
    presentation.tokensUsed !== undefined
    || presentation.inputTokens !== undefined
    || presentation.outputTokens !== undefined
    || presentation.estimatedCostMicrousd !== undefined
    || presentation.tokenBudget !== undefined
    || presentation.timeUsedSeconds !== undefined;

  return (
    <section className="chatapp-tool-call-panel chatapp-runtime-step-panel" role="region" aria-label={`${presentation.eyebrow} details`}>
      <header className="chatapp-tool-call-panel__header">
        <div className="chatapp-tool-call-panel__header-copy">
          <p className="chatapp-tool-call-panel__eyebrow">{presentation.eyebrow}</p>
          <h3 className="chatapp-tool-call-panel__title">{presentation.title}</h3>
          <div className="chatapp-tool-call-panel__badges">
            {presentation.status ? <span className="chat-ui-badge chat-ui-badge--neutral">{presentation.status}</span> : null}
            {presentation.provider ? <span className="chat-ui-badge chat-ui-badge--neutral">{presentation.provider}</span> : null}
            <span className="chat-ui-badge chat-ui-badge--neutral">{presentation.eventType}</span>
          </div>
        </div>
      </header>
      <div className="chatapp-tool-call-panel__content">
        {presentation.description ? <RuntimePanelText title="State" value={presentation.description} /> : null}
        {presentation.objective ? <RuntimePanelText title="Objective" value={presentation.objective} /> : null}
        {hasUsage ? <RuntimeUsage presentation={presentation} /> : null}
        <details className="chatapp-runtime-step-panel__technical">
          <summary>Technical details</summary>
          <pre className="chatapp-tool-call-panel__pre">
            <code>{formatTechnicalPayload(step.detail.raw ?? step.detail)}</code>
          </pre>
        </details>
      </div>
    </section>
  );
}

function RuntimePanelText({ title, value }: { title: string; value: string }) {
  return (
    <section className="chatapp-tool-call-panel__section">
      <h4 className="chatapp-tool-call-panel__section-title">{title}</h4>
      <div className="chatapp-tool-call-panel__section-body">
        <p className="chatapp-tool-call-panel__text">{value}</p>
      </div>
    </section>
  );
}

function RuntimeUsage({ presentation }: { presentation: RuntimeStepPresentation }) {
  const tokenUsage = formatTokenUsage(presentation.tokensUsed, presentation.tokenBudget);
  return (
    <section className="chatapp-tool-call-panel__section">
      <h4 className="chatapp-tool-call-panel__section-title">Usage</h4>
      <dl className="chatapp-runtime-step-panel__metrics">
        {tokenUsage ? (
          <div>
            <dt>Tokens</dt>
            <dd>{tokenUsage}</dd>
          </div>
        ) : null}
        {presentation.timeUsedSeconds !== undefined ? (
          <div>
            <dt>Elapsed</dt>
            <dd>{formatDuration(presentation.timeUsedSeconds)}</dd>
          </div>
        ) : null}
        {presentation.inputTokens !== undefined ? <div><dt>Input</dt><dd>{presentation.inputTokens.toLocaleString()} tokens</dd></div> : null}
        {presentation.outputTokens !== undefined ? <div><dt>Output</dt><dd>{presentation.outputTokens.toLocaleString()} tokens</dd></div> : null}
        {presentation.estimatedCostMicrousd !== undefined ? <div><dt>Estimated cost</dt><dd>{formatMicrousd(presentation.estimatedCostMicrousd)}</dd></div> : null}
      </dl>
    </section>
  );
}

function runtimeStepPresentation(step: RuntimeStep): RuntimeStepPresentation {
  const detail = step.detail;
  const raw = recordValue(detail.raw) ?? {};
  const item = recordValue(raw.item) ?? {};
  const goal = recordValue(item.goal) ?? recordValue(raw.goal) ?? recordValue(detail.goal) ?? {};
  const eventType = runtimeEventType(detail);
  const goalEvent = isGoalEvent(eventType);
  const cleared = normalizeEventType(eventType).endsWith(".cleared");
  const status = stringValue(goal.status) || stringValue(detail.status);
  const displayStatus = humanize(status);
  const objective = stringValue(goal.objective) || stringValue(goal.description);
  const provider = stringValue(detail.provider) || stringValue(detail.provider_id) || stringValue(raw.provider);
  const tokensUsed = firstNumber(goal.tokensUsed, goal.tokens_used, goal.tokenUsage, goal.token_usage);
  const tokenBudget = firstNumber(goal.tokenBudget, goal.token_budget);
  const timeUsedSeconds = firstNumber(goal.timeUsedSeconds, goal.time_used_seconds, goal.elapsedSeconds, goal.elapsed_seconds);
  const inputTokens = firstNumber(detail.input_tokens, raw.input_tokens);
  const outputTokens = firstNumber(detail.output_tokens, raw.output_tokens);
  const estimatedCostMicrousd = firstNumber(detail.estimated_cost_microusd, raw.estimated_cost_microusd);

  if (normalizeEventType(eventType) === "provider.usage") {
    return {
      description: "Usage reported by the pinned model provider for this inference step.",
      eventType,
      eyebrow: "Provider usage",
      label: "Provider usage",
      objective: "",
      provider,
      status: "Reported",
      title: "Tokens and estimated cost",
      inputTokens,
      outputTokens,
      estimatedCostMicrousd,
    };
  }

  if (goalEvent) {
    const title = cleared ? "No active goal" : displayStatus || (objective ? "Goal updated" : "Goal status updated");
    return {
      description: cleared ? "No active goal is currently associated with this provider thread." : "",
      eventType,
      eyebrow: "Goal status",
      label: cleared ? "Goal status · No active goal" : `Goal status · ${title}`,
      objective,
      provider,
      status: cleared ? "" : displayStatus,
      timeUsedSeconds,
      title,
      tokenBudget,
      tokensUsed,
    };
  }

  return {
    description: stringValue(detail.message) || "A structured provider event was received for this runtime thread.",
    eventType,
    eyebrow: "Runtime event",
    label: step.label,
    objective: "",
    provider,
    status: humanize(stringValue(detail.status)),
    title: step.label,
  };
}

function runtimeEventType(detail: Record<string, unknown>): string {
  const raw = recordValue(detail.raw);
  return stringValue(detail.provider_event_type) || stringValue(raw?.type);
}

function isGoalEvent(eventType: string): boolean {
  return normalizeEventType(eventType).startsWith("thread.goal.");
}

function normalizeEventType(value: string): string {
  return value.replace(/[\/_-]+/g, ".").replace(/\.+/g, ".").toLowerCase();
}

function humanize(value: string): string {
  if (!value) {
    return "";
  }
  const normalized = value
    .replace(/([a-z])([A-Z])/g, "$1 $2")
    .replace(/[._/-]+/g, " ")
    .replace(/\s+/g, " ")
    .trim()
    .toLowerCase();
  return normalized ? `${normalized.charAt(0).toUpperCase()}${normalized.slice(1)}` : "";
}

function recordValue(value: unknown): Record<string, unknown> | null {
  return value && typeof value === "object" && !Array.isArray(value) ? (value as Record<string, unknown>) : null;
}

function stringValue(value: unknown): string {
  return typeof value === "string" ? value.trim() : "";
}

function firstNumber(...values: unknown[]): number | undefined {
  return values.find((value): value is number => typeof value === "number" && Number.isFinite(value));
}

function formatTokenUsage(tokensUsed?: number, tokenBudget?: number): string {
  if (tokensUsed === undefined && tokenBudget === undefined) {
    return "";
  }
  const formatter = new Intl.NumberFormat("en-US");
  if (tokensUsed !== undefined && tokenBudget !== undefined) {
    return `${formatter.format(tokensUsed)} of ${formatter.format(tokenBudget)}`;
  }
  return formatter.format(tokensUsed ?? tokenBudget ?? 0);
}

function formatDuration(seconds: number): string {
  if (seconds < 60) {
    return `${Math.round(seconds)}s`;
  }
  const minutes = Math.floor(seconds / 60);
  const remainder = Math.round(seconds % 60);
  return remainder ? `${minutes}m ${remainder}s` : `${minutes}m`;
}

function formatMicrousd(value: number): string {
  return new Intl.NumberFormat(undefined, {
    style: "currency",
    currency: "USD",
    maximumFractionDigits: 6,
  }).format(value / 1_000_000);
}

function formatTechnicalPayload(value: unknown): string {
  const serialized = JSON.stringify(value, null, 2) ?? String(value);
  const maxLength = 12_000;
  return serialized.length > maxLength ? `${serialized.slice(0, maxLength)}\n… payload truncated` : serialized;
}
