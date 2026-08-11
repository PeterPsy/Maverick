import { useEffect, useState } from "react";
import type { SourceAppChatMode } from "../api/client";
import { requestJson } from "../api/http";

type SourceAppCapabilities = {
  label?: string;
  modes?: SourceAppChatMode[];
  supported?: Record<string, boolean | string>;
  unavailable?: Record<string, string>;
};

const SUPPORTED_LABELS: Record<string, string> = {
  storage_attachments: "Storage attachments",
  project_references: "Project references",
  project_files: "Project files and active canvas",
  active_design_context: "Active design context",
  design_system_selection: "Design system selection",
  skills: "Skills and @ mentions",
  agent_and_model: "Maverick agent and model",
  stop: "Stop current run",
  retry: "Retry failed message",
};

const UNAVAILABLE_LABELS: Record<string, string> = {
  plugins: "Plugins",
  mcp: "MCP servers",
  connectors: "Connectors",
  library: "Library",
  figma_import: "Figma .fig import",
  local_code: "Local code and working directory",
  external_search: "External search",
  media_generation: "Direct media generation",
  terminal_and_deploy: "Terminal and deploy",
  design_system_mutation: "Design-system mutation",
  visual_annotations: "Visual comments and annotations",
};

export function SourceAppChatTools({
  disabled,
  mode,
  onSelectMode,
  projectId,
  sourceAppId,
}: {
  disabled: boolean;
  mode: SourceAppChatMode;
  onSelectMode: (mode: SourceAppChatMode) => void;
  projectId: string;
  sourceAppId: string;
}) {
  const [open, setOpen] = useState(false);
  const [capabilities, setCapabilities] = useState<SourceAppCapabilities | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!open || capabilities || !sourceAppId) {
      return;
    }
    const abortController = new AbortController();
    requestJson<SourceAppCapabilities>(`/api/apps/${encodeURIComponent(sourceAppId)}/backend`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      signal: abortController.signal,
      body: JSON.stringify({ action: "chat.capabilities" }),
    })
      .then((payload) => {
        setCapabilities(payload);
        setError("");
      })
      .catch((loadError) => {
        if (!abortController.signal.aborted) {
          setError(loadError instanceof Error ? loadError.message : "OpenDesign options are unavailable.");
        }
      });
    return () => abortController.abort();
  }, [capabilities, open, sourceAppId]);

  const modes = capabilities?.modes?.length ? capabilities.modes : (["chat", "plan", "design"] as SourceAppChatMode[]);
  return (
    <div className="chatapp-source-tools">
      <button
        aria-expanded={open}
        aria-haspopup="menu"
        aria-label="OpenDesign options"
        className={`chatapp-composer__tool-button chatapp-source-tools__button ${open ? "is-active" : ""}`}
        disabled={disabled}
        onClick={() => setOpen((current) => !current)}
        title="OpenDesign options"
        type="button"
      >
        <span aria-hidden="true" className="material-symbols-rounded">design_services</span>
        <span className="chatapp-source-tools__label">{modeLabel(mode)}</span>
      </button>
      {open ? (
        <div aria-label="OpenDesign options" className="chatapp-source-tools__menu" role="menu">
          <div className="chatapp-source-tools__header">
            <span className="chatapp-source-tools__badge">OpenDesign</span>
            <span>{projectId ? "Project connected" : "Select a project"}</span>
          </div>
          <div className="chatapp-source-tools__section-label">Mode</div>
          <div className="chatapp-source-tools__modes">
            {modes.map((item) => (
              <button
                aria-checked={mode === item}
                className="chatapp-source-tools__mode"
                key={item}
                onClick={() => {
                  onSelectMode(item);
                  setOpen(false);
                }}
                role="menuitemradio"
                type="button"
              >
                <span aria-hidden="true" className="material-symbols-rounded">
                  {mode === item ? "radio_button_checked" : "radio_button_unchecked"}
                </span>
                {modeLabel(item)}
              </button>
            ))}
          </div>
          {error ? <p className="chatapp-source-tools__error">{error}</p> : null}
          {!capabilities && !error ? <p className="chatapp-source-tools__status">Loading governed capabilities…</p> : null}
          {capabilities?.supported ? (
            <>
              <div className="chatapp-source-tools__section-label">Available here</div>
              <div className="chatapp-source-tools__list">
                {Object.entries(capabilities.supported).map(([key]) => (
                  <div className="chatapp-source-tools__item" key={key}>
                    <span aria-hidden="true" className="material-symbols-rounded">check_circle</span>
                    <span>{SUPPORTED_LABELS[key] || humanize(key)}</span>
                  </div>
                ))}
              </div>
            </>
          ) : null}
          {capabilities?.unavailable ? (
            <>
              <div className="chatapp-source-tools__section-label">Unavailable in the sandbox</div>
              <div className="chatapp-source-tools__list">
                {Object.entries(capabilities.unavailable).map(([key, reason]) => (
                  <div className="chatapp-source-tools__item is-disabled" key={key} title={reason}>
                    <span aria-hidden="true" className="material-symbols-rounded">block</span>
                    <span>{UNAVAILABLE_LABELS[key] || humanize(key)}</span>
                    <small>{reason}</small>
                  </div>
                ))}
              </div>
            </>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}

function modeLabel(mode: SourceAppChatMode): string {
  return mode === "chat" ? "Chat" : mode === "plan" ? "Plan" : "Design";
}

function humanize(value: string): string {
  return value.replaceAll("_", " ").replace(/^./, (character) => character.toUpperCase());
}
