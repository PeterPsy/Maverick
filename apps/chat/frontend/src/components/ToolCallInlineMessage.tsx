import { useEffect, useState } from "react";
import {
  decideRuntimeToolConfirmation,
  getRuntimeToolConfirmation,
  type RuntimeToolConfirmation,
  type ToolCallMessage,
} from "../api/client";
import { isNoisyRuntimeLabel } from "../lib/runtimeStepLabels";
import { toolActivityLabel } from "../lib/toolPresentation";
import { ActivityDisclosure } from "./ActivityDisclosure";

type ToolCallInlineMessageProps = {
  createdAt?: string;
  defaultExpanded?: boolean;
  toolCalls: ToolCallMessage[];
};

export function ToolCallInlineMessage({ createdAt, defaultExpanded = true, toolCalls }: ToolCallInlineMessageProps) {
  const [selectedToolKey, setSelectedToolKey] = useState<string | null>(null);
  const toolCount = toolCalls.length;
  const activityCreatedAt = createdAt || toolCalls.find((toolCall) => toolCall.createdAt)?.createdAt;

  useEffect(() => {
    if (selectedToolKey && !toolCalls.some((toolCall, index) => toolRenderKey(toolCall, index) === selectedToolKey)) {
      setSelectedToolKey(null);
    }
  }, [selectedToolKey, toolCalls]);

  useEffect(() => {
    if (selectedToolKey) return;
    const pendingIndex = toolCalls.findIndex((toolCall) => toolCall.status === "awaiting_confirmation");
    if (pendingIndex >= 0) {
      setSelectedToolKey(toolRenderKey(toolCalls[pendingIndex], pendingIndex));
    }
  }, [selectedToolKey, toolCalls]);

  return (
    <ActivityDisclosure
      createdAt={activityCreatedAt}
      defaultExpanded={defaultExpanded}
      label={`${toolCalls.some((item) => item.status === "awaiting_confirmation") ? "Tool confirmation required" : "Actions"}${toolCount > 1 ? ` (${toolCount})` : ""}`}
    >
      {toolCalls.map((toolCall, index) => {
        const renderKey = toolRenderKey(toolCall, index);
        const isSelected = selectedToolKey === renderKey;
        const panelId = `chatapp-tool-call-panel-${renderKey.replace(/[^A-Za-z0-9_-]/g, "-")}`;
        return (
          <div className="chatapp-tool-inline__item" key={renderKey}>
            <button
              aria-controls={panelId}
              aria-expanded={isSelected}
              className={`chatapp-tool-inline__row ${toolCall.status === "failed" ? "is-failed" : ""} ${
                toolCall.status === "started" || toolCall.status === "updated" || toolCall.status === "awaiting_confirmation" ? "is-active" : ""
              } ${isSelected ? "is-selected" : ""}`}
              onClick={() => {
                setSelectedToolKey(isSelected ? null : renderKey);
              }}
              type="button"
            >
              <ToolStatusIcon status={toolCall.status} />
              <span className="chatapp-tool-inline__label">{displayToolName(toolCall)}</span>
              <span className={`chatapp-tool-inline__row-chevron ${isSelected ? "is-expanded" : ""}`} aria-hidden="true">
                <span className="material-symbols-rounded">expand_more</span>
              </span>
            </button>
            {isSelected ? <ToolCallPanel id={panelId} toolCall={toolCall} /> : null}
          </div>
        );
      })}
    </ActivityDisclosure>
  );
}

function ToolStatusIcon({ status }: { status: ToolCallMessage["status"] }) {
  const icon = status === "failed" ? "error" : status === "completed" ? "check_circle" : status === "awaiting_confirmation" ? "approval" : "progress_activity";
  const animationClass = status === "started" || status === "updated" ? "chatapp-tool-inline__stroke--spin" : "";
  return (
    <span className="chatapp-tool-inline__icon" aria-hidden="true">
      <span className={`material-symbols-rounded ${animationClass}`}>{icon}</span>
    </span>
  );
}

function ToolCallPanel({ id, toolCall }: { id: string; toolCall: ToolCallMessage }) {
  const summary = toolSummary(toolCall.detail);
  const command = stringValue(toolCall.detail.command) || stringValue(toolCall.detail.cmd);
  const query = stringValue(toolCall.detail.query);
  const webResults = arrayRecords(toolCall.detail.results);
  const fileChanges = arrayRecords(toolCall.detail.changes);
  const patch = stringValue(toolCall.detail.patch);
  const output = stringValue(toolCall.detail.output) || stringValue(toolCall.detail.stdout);
  const error = stringValue(toolCall.detail.error) || stringValue(toolCall.detail.stderr);

  return (
    <section className="chatapp-tool-call-panel" id={id} role="region" aria-label={`Dettagli tool ${displayToolName(toolCall)}`}>
      <header className="chatapp-tool-call-panel__header">
        <div className="chatapp-tool-call-panel__header-copy">
          <p className="chatapp-tool-call-panel__eyebrow">Tool Call</p>
          <h3 className="chatapp-tool-call-panel__title">{displayToolName(toolCall)}</h3>
          <div className="chatapp-tool-call-panel__badges">
            <span className="chat-ui-badge chat-ui-badge--neutral">{toolCall.status}</span>
            {toolCall.createdAt ? <span className="chat-ui-badge chat-ui-badge--neutral">{formatToolTime(toolCall.createdAt)}</span> : null}
          </div>
        </div>
      </header>
      <div className="chatapp-tool-call-panel__content">
        {summary ? <ToolPanelText title="Summary" value={summary} /> : null}
        {query ? <ToolPanelText title="Query" value={query} /> : null}
        {webResults.length ? <ToolPanelWebResults results={webResults} /> : null}
        {command ? <ToolPanelCode title="Command" value={command} /> : null}
        {fileChanges.length ? <ToolPanelFileChanges changes={fileChanges} /> : null}
        {patch ? <ToolPanelCode title="Patch" value={patch} /> : null}
        {output ? <ToolPanelCode title="Output" value={output} /> : null}
        {error ? <ToolPanelCode title="Error" value={error} isError /> : null}
        {toolCall.status === "awaiting_confirmation" ? <ToolConfirmationPanel toolCall={toolCall} /> : null}
        <ToolPanelCode title="Raw Payload" value={JSON.stringify(toolCall.detail, null, 2)} />
      </div>
    </section>
  );
}

function ToolConfirmationPanel({ toolCall }: { toolCall: ToolCallMessage }) {
  const turnId = stringValue(toolCall.detail.turn_id);
  const invocationId = stringValue(toolCall.detail.invocation_id);
  const [confirmation, setConfirmation] = useState<RuntimeToolConfirmation | null>(null);
  const [error, setError] = useState("");
  const [decisionPending, setDecisionPending] = useState<"approve" | "deny" | null>(null);

  useEffect(() => {
    let active = true;
    if (!turnId || !invocationId) {
      setError("Confirmation identity is unavailable.");
      return () => { active = false; };
    }
    getRuntimeToolConfirmation(turnId, invocationId)
      .then((payload) => {
        if (active) setConfirmation(payload);
      })
      .catch((loadError) => {
        if (active) setError(loadError instanceof Error ? loadError.message : "Unable to load confirmation state.");
      });
    return () => { active = false; };
  }, [invocationId, turnId]);

  const invocation = confirmation?.invocation;
  const argumentsDigest = invocation?.arguments_digest || stringValue(toolCall.detail.arguments_digest);
  const invocationRevision = invocation?.revision ?? numberValue(toolCall.detail.invocation_revision);
  const decided = Boolean(confirmation?.confirmation);

  async function decide(decision: "approve" | "deny") {
    if (!turnId || !invocationId || !argumentsDigest || invocationRevision === null) return;
    setDecisionPending(decision);
    setError("");
    try {
      setConfirmation(await decideRuntimeToolConfirmation(turnId, invocationId, {
        decision,
        arguments_digest: argumentsDigest,
        expected_invocation_revision: invocationRevision,
      }));
    } catch (decisionError) {
      setError(decisionError instanceof Error ? decisionError.message : "Unable to record confirmation.");
    } finally {
      setDecisionPending(null);
    }
  }

  return (
    <section className="chatapp-tool-confirmation" aria-label="Tool confirmation">
      <div className="chatapp-tool-confirmation__heading">
        <span aria-hidden="true" className="material-symbols-rounded">verified_user</span>
        <span>
          <strong>Confirmation required</strong>
          <small>This one-shot decision is bound to the exact argument digest and current policy revision.</small>
        </span>
      </div>
      <dl className="chatapp-tool-confirmation__facts">
        <div><dt>Tool</dt><dd>{invocation?.tool_handle || stringValue(toolCall.detail.tool_handle) || toolCall.name}</dd></div>
        <div><dt>Effect</dt><dd>{invocation?.effect_class || stringValue(toolCall.detail.effect_class) || "unclassified"}</dd></div>
        <div><dt>Scope</dt><dd>Current invocation only</dd></div>
        <div><dt>Policy</dt><dd>{invocation?.policy_revision || "Current effective authority"}</dd></div>
        <div><dt>Argument digest</dt><dd>{argumentsDigest ? `${argumentsDigest.slice(0, 16)}…` : "Unavailable"}</dd></div>
        <div><dt>TTL</dt><dd>{confirmation?.confirmation?.expires_at || confirmation?.confirmation_deadline_at ? formatConfirmationExpiry(confirmation.confirmation?.expires_at || confirmation.confirmation_deadline_at || "") : "Current turn budget"}</dd></div>
      </dl>
      <ToolPanelCode
        title="Canonical argument summary"
        value={JSON.stringify(invocation?.arguments_summary || toolCall.detail.arguments_summary || {}, null, 2)}
      />
      {decided ? (
        <p className="chatapp-tool-confirmation__receipt" role="status">
          Decision recorded · {confirmation?.confirmation?.state}
        </p>
      ) : (
        <div className="chatapp-tool-confirmation__actions">
          <button disabled={Boolean(decisionPending) || invocationRevision === null} onClick={() => void decide("approve")} type="button">
            <span aria-hidden="true" className="material-symbols-rounded">check</span>
            {decisionPending === "approve" ? "Approving" : "Approve once"}
          </button>
          <button className="is-deny" disabled={Boolean(decisionPending) || invocationRevision === null} onClick={() => void decide("deny")} type="button">
            <span aria-hidden="true" className="material-symbols-rounded">close</span>
            {decisionPending === "deny" ? "Denying" : "Deny"}
          </button>
        </div>
      )}
      {error ? <p className="chatapp-tool-confirmation__error" role="alert">{error}</p> : null}
    </section>
  );
}

function numberValue(value: unknown): number | null {
  return typeof value === "number" && Number.isInteger(value) && value >= 0 ? value : null;
}

function formatConfirmationExpiry(value: string): string {
  const expiry = new Date(value);
  if (Number.isNaN(expiry.getTime())) return value;
  return `expires ${new Intl.DateTimeFormat(undefined, { dateStyle: "medium", timeStyle: "short" }).format(expiry)}`;
}

function ToolPanelWebResults({ results }: { results: Record<string, unknown>[] }) {
  return (
    <section className="chatapp-tool-call-panel__section">
      <h4 className="chatapp-tool-call-panel__section-title">Results</h4>
      <div className="chatapp-tool-call-panel__list">
        {results.map((result, index) => {
          const title = stringValue(result.title) || "Untitled result";
          const url = stringValue(result.url);
          const snippet = stringValue(result.snippet);
          return (
            <div className="chatapp-tool-call-panel__list-item" key={`${title}-${index}`}>
              {url ? (
                <a href={url} rel="noreferrer" target="_blank">
                  {title}
                </a>
              ) : (
                <strong>{title}</strong>
              )}
              {snippet ? <p>{snippet}</p> : null}
            </div>
          );
        })}
      </div>
    </section>
  );
}

function ToolPanelFileChanges({ changes }: { changes: Record<string, unknown>[] }) {
  return (
    <section className="chatapp-tool-call-panel__section">
      <h4 className="chatapp-tool-call-panel__section-title">Changes</h4>
      <div className="chatapp-tool-call-panel__list">
        {changes.map((change, index) => {
          const path = stringValue(change.path) || "Unknown path";
          const changeType = stringValue(change.changeType) || "edit";
          const movePath = stringValue(change.movePath);
          return (
            <div className="chatapp-tool-call-panel__list-item" key={`${path}-${index}`}>
              <strong>{path}</strong>
              <p>{movePath ? `${changeType} to ${movePath}` : changeType}</p>
            </div>
          );
        })}
      </div>
    </section>
  );
}

function ToolPanelText({ title, value }: { title: string; value: string }) {
  return (
    <section className="chatapp-tool-call-panel__section">
      <h4 className="chatapp-tool-call-panel__section-title">{title}</h4>
      <div className="chatapp-tool-call-panel__section-body">
        <p className="chatapp-tool-call-panel__text">{value}</p>
      </div>
    </section>
  );
}

function ToolPanelCode({ isError = false, title, value }: { isError?: boolean; title: string; value: string }) {
  return (
    <section className="chatapp-tool-call-panel__section">
      <h4 className="chatapp-tool-call-panel__section-title">{title}</h4>
      <pre className={`chatapp-tool-call-panel__pre ${isError ? "is-error" : ""}`}>
        <code>{value}</code>
      </pre>
    </section>
  );
}

function toolSummary(detail: Record<string, unknown>): string {
  const message = stringValue(detail.message) || stringValue(detail.label) || stringValue(detail.summary);
  if (message) {
    return isNoisyRuntimeLabel(message) ? "" : message;
  }
  const exitCode = detail.exit_code;
  if (typeof exitCode === "number") {
    return `Command exited with code ${exitCode}.`;
  }
  const providerEventType = stringValue(detail.provider_event_type);
  return providerEventType ? `Provider event: ${providerEventType}` : "";
}

function displayToolName(toolCall: ToolCallMessage): string {
  return toolActivityLabel({ detail: toolCall.detail, name: toolCall.name, status: toolCall.status });
}

function stringValue(value: unknown): string {
  return typeof value === "string" ? value.trim() : "";
}

function arrayRecords(value: unknown): Record<string, unknown>[] {
  return Array.isArray(value) ? value.filter((item): item is Record<string, unknown> => Boolean(item) && typeof item === "object" && !Array.isArray(item)) : [];
}

function toolRenderKey(toolCall: ToolCallMessage, index: number): string {
  return toolCall.id || `${toolCall.name}-${index}`;
}

function formatToolTime(value: string): string {
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) {
    return "";
  }
  return new Intl.DateTimeFormat("en-US", {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  }).format(parsed);
}
