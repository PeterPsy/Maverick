import { useState } from "react";
import type { CSSProperties } from "react";
import { createPortal } from "react-dom";
import type { ToolCallMessage } from "../api/client";
import { isNoisyRuntimeLabel } from "../lib/runtimeStepLabels";

type PanelAnchor = {
  left: number;
  top: number;
};

type ToolCallInlineMessageProps = {
  toolCalls: ToolCallMessage[];
};

export function ToolCallInlineMessage({ toolCalls }: ToolCallInlineMessageProps) {
  const [isExpanded, setIsExpanded] = useState(true);
  const [selectedTool, setSelectedTool] = useState<ToolCallMessage | null>(null);
  const [panelAnchor, setPanelAnchor] = useState<PanelAnchor | null>(null);
  const toolCount = toolCalls.length;

  return (
    <div className="chatapp-tool-inline">
      <button className="chatapp-tool-inline__toggle" onClick={() => setIsExpanded((current) => !current)} type="button">
        <span className={`chatapp-tool-inline__chevron ${isExpanded ? "is-expanded" : ""}`} aria-hidden="true">
          <span className="material-symbols-rounded">expand_more</span>
        </span>
        <span className="chatapp-tool-inline__toggle-label">Tool Used{toolCount > 1 ? ` (${toolCount})` : ""}</span>
      </button>
      <div className={`chatapp-tool-inline__body ${isExpanded ? "" : "is-collapsed"}`}>
        <div className="chatapp-tool-inline__body-inner">
          {toolCalls.map((toolCall, index) => (
            <button
              className={`chatapp-tool-inline__row ${toolCall.status === "failed" ? "is-failed" : ""} ${
                toolCall.status === "started" || toolCall.status === "updated" ? "is-active" : ""
              } ${selectedTool?.id === toolCall.id && toolCall.id ? "is-selected" : ""}`}
              key={toolCall.id || `${toolCall.name}-${index}`}
              onClick={(event) => {
                setPanelAnchor(panelAnchorFromElement(event.currentTarget));
                setSelectedTool(toolCall);
              }}
              type="button"
            >
              <ToolStatusIcon status={toolCall.status} />
              <span className="chatapp-tool-inline__label">{displayToolName(toolCall)}</span>
            </button>
          ))}
        </div>
      </div>
      {selectedTool ? (
        <ToolCallPanel
          anchor={panelAnchor}
          toolCall={selectedTool}
          onClose={() => {
            setSelectedTool(null);
            setPanelAnchor(null);
          }}
        />
      ) : null}
    </div>
  );
}

function ToolStatusIcon({ status }: { status: ToolCallMessage["status"] }) {
  const icon = status === "failed" ? "error" : status === "completed" ? "check_circle" : "progress_activity";
  const animationClass = status === "started" || status === "updated" ? "chatapp-tool-inline__stroke--spin" : "";
  return (
    <span className="chatapp-tool-inline__icon" aria-hidden="true">
      <span className={`material-symbols-rounded ${animationClass}`}>{icon}</span>
    </span>
  );
}

function ToolCallPanel({ anchor, onClose, toolCall }: { anchor: PanelAnchor | null; onClose: () => void; toolCall: ToolCallMessage }) {
  const summary = toolSummary(toolCall.detail);
  const command = stringValue(toolCall.detail.command) || stringValue(toolCall.detail.cmd);
  const query = stringValue(toolCall.detail.query);
  const webResults = arrayRecords(toolCall.detail.results);
  const fileChanges = arrayRecords(toolCall.detail.changes);
  const patch = stringValue(toolCall.detail.patch);
  const output = stringValue(toolCall.detail.output) || stringValue(toolCall.detail.stdout);
  const error = stringValue(toolCall.detail.error) || stringValue(toolCall.detail.stderr);

  const panel = (
    <div className="chatapp-tool-call-panel-layer" onClick={onClose}>
      <aside
        className="chatapp-tool-call-panel is-right"
        onClick={(event) => event.stopPropagation()}
        role="dialog"
        aria-label={displayToolName(toolCall)}
        style={anchor ? ({ "--chatapp-tool-call-panel-left": `${anchor.left}px`, "--chatapp-tool-call-panel-top": `${anchor.top}px` } as CSSProperties) : undefined}
      >
        <header className="chatapp-tool-call-panel__header">
          <div className="chatapp-tool-call-panel__header-copy">
            <p className="chatapp-tool-call-panel__eyebrow">Tool Call</p>
            <h3 className="chatapp-tool-call-panel__title">{displayToolName(toolCall)}</h3>
            <div className="chatapp-tool-call-panel__badges">
              <span className="chat-ui-badge chat-ui-badge--secondary">{toolCall.status}</span>
              {toolCall.createdAt ? <span className="chat-ui-badge chat-ui-badge--secondary">{formatToolTime(toolCall.createdAt)}</span> : null}
            </div>
          </div>
          <button className="chatapp-tool-call-panel__close" onClick={onClose} type="button" aria-label="Chiudi dettaglio tool">
            <span className="material-symbols-rounded" aria-hidden="true">
              close
            </span>
          </button>
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
          <ToolPanelCode title="Raw Payload" value={JSON.stringify(toolCall.detail, null, 2)} />
        </div>
      </aside>
    </div>
  );
  return createPortal(panel, document.body);
}

function panelAnchorFromElement(element: HTMLElement): PanelAnchor {
  const rect = element.getBoundingClientRect();
  const panelWidth = Math.min(360, Math.max(280, window.innerWidth - 24));
  const gap = 12;
  const rightSideLeft = rect.right + gap;
  const left = rightSideLeft + panelWidth <= window.innerWidth - gap ? rightSideLeft : Math.max(gap, rect.left - panelWidth - gap);
  const top = Math.min(Math.max(gap, rect.top - 12), Math.max(gap, window.innerHeight - 460));
  return { left, top };
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
  const toolKind = stringValue(toolCall.detail.tool_kind);
  if (toolKind === "web_search") {
    return "Web search";
  }
  if (toolKind === "file_change") {
    return "File changes";
  }
  if (toolKind === "skill_change") {
    return "Skills changed";
  }
  if (toolKind === "command") {
    return commandLabel(stringValue(toolCall.detail.command));
  }
  const command = stringValue(toolCall.detail.command);
  if (command) {
    return commandLabel(command);
  }
  const providerEventType = stringValue(toolCall.detail.provider_event_type);
  if (providerEventType.includes("web_search")) {
    return "Web search";
  }
  if (providerEventType.includes("file")) {
    return "File operation";
  }
  if (toolCall.name.includes("web")) {
    return "Web search";
  }
  return toolCall.name;
}

function commandLabel(command: string): string {
  if (!command) {
    return "Command";
  }
  const normalized = command.toLowerCase();
  if (/(^|\s)(rg|find|ls|pwd)(\s|$)/.test(normalized) || normalized.includes("rg --files")) {
    return "File search";
  }
  if (/(^|\s)(cat|sed|tail|head|nl)(\s|$)/.test(normalized)) {
    return "File read";
  }
  if (normalized.includes("apply_patch") || normalized.includes("npm run build") || normalized.includes("python3.12 -m unittest")) {
    return "Command";
  }
  if (/(^|\s)(cp|mv|mkdir|touch)(\s|$)/.test(normalized)) {
    return "File change";
  }
  return "Shell command";
}

function stringValue(value: unknown): string {
  return typeof value === "string" ? value.trim() : "";
}

function arrayRecords(value: unknown): Record<string, unknown>[] {
  return Array.isArray(value) ? value.filter((item): item is Record<string, unknown> => Boolean(item) && typeof item === "object" && !Array.isArray(item)) : [];
}

function formatToolTime(value: string): string {
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) {
    return "";
  }
  return new Intl.DateTimeFormat("it-IT", {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  }).format(parsed);
}
