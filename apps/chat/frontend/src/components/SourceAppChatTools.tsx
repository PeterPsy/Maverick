import { useEffect, useRef, useState } from "react";
import type { SourceAppChatMode } from "../api/client";
import { requestJson } from "../api/http";
import { sourceAppPresentation } from "../lib/sourceAppPresentation";

type SourceAppCapabilities = {
  label?: string;
  modes?: SourceAppChatMode[];
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
  const controlRef = useRef<HTMLDivElement | null>(null);
  const triggerRef = useRef<HTMLButtonElement | null>(null);

  useEffect(() => {
    setCapabilities(null);
    setError("");
    setOpen(false);
  }, [sourceAppId]);

  useEffect(() => {
    if (!open) {
      return;
    }

    function handlePointerDown(event: PointerEvent) {
      const target = event.target as Node | null;
      if (!target || controlRef.current?.contains(target)) {
        return;
      }
      setOpen(false);
    }

    function handleKeyDown(event: KeyboardEvent) {
      if (event.key !== "Escape") {
        return;
      }
      setOpen(false);
      triggerRef.current?.focus();
    }

    document.addEventListener("pointerdown", handlePointerDown);
    document.addEventListener("keydown", handleKeyDown);
    return () => {
      document.removeEventListener("pointerdown", handlePointerDown);
      document.removeEventListener("keydown", handleKeyDown);
    };
  }, [open]);

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
          setError(loadError instanceof Error ? loadError.message : "Source app options are unavailable.");
        }
      });
    return () => abortController.abort();
  }, [capabilities, open, sourceAppId]);

  const modes = capabilities?.modes || [];
  const presentation = sourceAppPresentation(sourceAppId);
  const label = capabilities?.label || presentation?.label || "Source app";
  return (
    <div className="chatapp-source-tools" ref={controlRef}>
      <button
        aria-expanded={open}
        aria-haspopup="menu"
        aria-label={`${label} options`}
        className={`chatapp-composer__tool-button chatapp-source-tools__button ${open ? "is-active" : ""}`}
        disabled={disabled}
        onClick={() => setOpen((current) => !current)}
        ref={triggerRef}
        title={`${label} options`}
        type="button"
      >
        <span aria-hidden="true" className="material-symbols-rounded">{presentation?.icon || "apps"}</span>
        <span className="chatapp-source-tools__label">{modeLabel(mode)}</span>
      </button>
      {open ? (
        <div aria-label={`${label} options`} className="chatapp-source-tools__menu" role="menu">
          <div className="chatapp-source-tools__header">
            <span className="chatapp-source-tools__badge">{label}</span>
            <span>{projectId ? "Project connected" : "Select a project"}</span>
          </div>
          {modes.length ? (
            <>
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
            </>
          ) : null}
          {error ? <p className="chatapp-source-tools__error">{error}</p> : null}
          {!capabilities && !error ? <p className="chatapp-source-tools__status">Loading governed capabilities…</p> : null}
        </div>
      ) : null}
    </div>
  );
}

function modeLabel(mode: SourceAppChatMode): string {
  return mode === "chat" ? "Chat" : mode === "plan" ? "Plan" : "Design";
}
