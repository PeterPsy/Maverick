import { useEffect, useId, useRef, useState } from "react";
import { createPortal } from "react-dom";
import type { ChatUsageSummary, TokenUsageBreakdown } from "../api/client";

const tokenNumber = new Intl.NumberFormat(undefined, { maximumFractionDigits: 0 });

export function ChatUsageBadge({ usage }: { usage: ChatUsageSummary | null }) {
  const [open, setOpen] = useState(false);
  const buttonRef = useRef<HTMLButtonElement | null>(null);
  const titleId = useId();

  useEffect(() => {
    if (!open) return;
    const onKeyDown = (event: globalThis.KeyboardEvent) => {
      if (event.key === "Escape") {
        setOpen(false);
        buttonRef.current?.focus();
      }
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [open]);

  if (!usage) return null;
  const contextLabel = usage.context_used_percent === null ? "Context —" : `${formatPercent(usage.context_used_percent)} context`;
  const tokenLabel = `${formatTokens(usage.tokens.total_tokens)} tokens`;
  return (
    <>
      <button
        aria-haspopup="dialog"
        aria-label={`Chat token usage: ${contextLabel}, ${tokenLabel}`}
        className="chatapp-usage-badge"
        onClick={() => setOpen(true)}
        ref={buttonRef}
        title="Open complete usage statistics for this chat"
        type="button"
      >
        <span aria-hidden="true" className="material-symbols-rounded">data_usage</span>
        <span>{contextLabel}</span>
        <span aria-hidden="true" className="chatapp-usage-badge__separator">·</span>
        <span>{tokenLabel}</span>
      </button>
      {open ? createPortal(
        <div className="chatapp-usage-modal-backdrop" onMouseDown={() => setOpen(false)}>
          <section
            aria-labelledby={titleId}
            aria-modal="true"
            className="chatapp-usage-modal"
            onMouseDown={(event) => event.stopPropagation()}
            role="dialog"
          >
            <header className="chatapp-usage-modal__header">
              <div>
                <p className="chatapp-usage-modal__eyebrow">Current chat</p>
                <h2 id={titleId}>Token usage</h2>
              </div>
              <button
                aria-label="Close token usage statistics"
                className="chatapp-usage-modal__close"
                onClick={() => {
                  setOpen(false);
                  buttonRef.current?.focus();
                }}
                type="button"
              >
                <span aria-hidden="true" className="material-symbols-rounded">close</span>
              </button>
            </header>

            <section className="chatapp-usage-modal__context" aria-label="Active context usage">
              <div className="chatapp-usage-modal__context-heading">
                <span>Active context</span>
                <strong>{usage.context_used_percent === null ? "Unavailable" : formatPercent(usage.context_used_percent)}</strong>
              </div>
              {usage.context_used_percent !== null ? (
                <div
                  aria-label={`${formatPercent(usage.context_used_percent)} of the context window used`}
                  aria-valuemax={100}
                  aria-valuemin={0}
                  aria-valuenow={usage.context_used_percent}
                  className="chatapp-usage-modal__progress"
                  role="progressbar"
                >
                  <span style={{ width: `${Math.max(0, Math.min(100, usage.context_used_percent))}%` }} />
                </div>
              ) : null}
              <p>
                {usage.context_tokens === null ? "The provider did not report the active context." : `${formatTokens(usage.context_tokens)} used`}
                {usage.context_window_tokens === null ? "" : ` of ${formatTokens(usage.context_window_tokens)} tokens`}
                {` · ${accuracyLabel(usage.context_accuracy)}`}
              </p>
            </section>

            <div className="chatapp-usage-modal__summary">
              <UsageMetric label="Chat total" value={formatTokens(usage.tokens.total_tokens)} />
              <UsageMetric label="Direct" value={formatTokens(usage.direct_tokens.total_tokens)} />
              <UsageMetric label="Delegated" value={formatTokens(usage.delegated_tokens.total_tokens)} />
              <UsageMetric
                label="Estimated cost"
                value={usage.estimated_cost_microusd === null ? "Unavailable" : formatCost(usage.estimated_cost_microusd)}
              />
            </div>

            <section className="chatapp-usage-modal__section">
              <h3>Token breakdown</h3>
              <UsageBreakdownTable tokens={usage.tokens} />
            </section>

            <section className="chatapp-usage-modal__section chatapp-usage-modal__metadata">
              <h3>Coverage and source</h3>
              <dl>
                <UsageDetail label="Providers" value={usage.provider_ids.join(", ") || "Unavailable"} />
                <UsageDetail label="Models" value={usage.model_ids.join(", ") || "Unavailable"} />
                <UsageDetail label="Token quality" value={accuracyLabel(usage.token_accuracy)} />
                <UsageDetail label="Samples" value={formatTokens(usage.sample_count)} />
                <UsageDetail label="Coverage since" value={formatTimestamp(usage.coverage_since)} />
                <UsageDetail label="Last update" value={formatTimestamp(usage.updated_at)} />
              </dl>
            </section>

            <p className="chatapp-usage-modal__note">
              Active context is the latest provider snapshot and may shrink after compaction. Chat total is cumulative and includes delegated runtime sessions.
            </p>
          </section>
        </div>,
        document.body,
      ) : null}
    </>
  );
}

function UsageMetric({ label, value }: { label: string; value: string }) {
  return <article><span>{label}</span><strong>{value}</strong></article>;
}

function UsageDetail({ label, value }: { label: string; value: string }) {
  return <><dt>{label}</dt><dd>{value}</dd></>;
}

function UsageBreakdownTable({ tokens }: { tokens: TokenUsageBreakdown }) {
  const rows = [
    ["Input (uncached)", tokens.input_tokens],
    ["Cached input", tokens.cached_input_tokens],
    ["Cache write", tokens.cache_write_input_tokens],
    ["Output", tokens.output_tokens],
    ["Reasoning output", tokens.reasoning_output_tokens],
  ] as const;
  return (
    <dl className="chatapp-usage-modal__breakdown">
      {rows.map(([label, value]) => <UsageDetail key={label} label={label} value={formatTokens(value)} />)}
    </dl>
  );
}

function formatTokens(value: number): string {
  return tokenNumber.format(Math.max(0, Number.isFinite(value) ? value : 0));
}

function formatPercent(value: number): string {
  const bounded = Math.max(0, Math.min(100, value));
  return `${Number.isInteger(bounded) ? bounded.toFixed(0) : bounded.toFixed(1)}%`;
}

function accuracyLabel(value: ChatUsageSummary["token_accuracy"]): string {
  if (value === "exact") return "Exact provider report";
  if (value === "estimated") return "Estimated";
  return "Unavailable";
}

function formatCost(microusd: number): string {
  return new Intl.NumberFormat(undefined, {
    style: "currency",
    currency: "USD",
    minimumFractionDigits: 2,
    maximumFractionDigits: 6,
  }).format(Math.max(0, microusd) / 1_000_000);
}

function formatTimestamp(value: string | null): string {
  if (!value) return "Unavailable";
  const timestamp = new Date(value);
  return Number.isNaN(timestamp.getTime()) ? "Unavailable" : timestamp.toLocaleString();
}
