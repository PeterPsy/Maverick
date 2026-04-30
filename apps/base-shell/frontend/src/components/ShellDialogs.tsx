import { useEffect, useMemo, useState } from "react";
import { PlatformSettings, ProviderModelOption, ProviderReasoningOption } from "../api";
import { Button, Dialog, Surface } from "../ui";
import { TutorialDialog } from "./TutorialDialog";

type ShellDialog = "settings" | "tutorial" | null;

const ACTIVE_RUNTIME_STATUSES = new Set(["created", "running", "stopping"]);

const FALLBACK_REASONING_OPTIONS: ProviderReasoningOption[] = [
  { effort: "low", label: "Low", description: "Fast responses with lighter reasoning" },
  { effort: "medium", label: "Mid", description: "Balanced reasoning depth" },
  { effort: "high", label: "High", description: "Greater reasoning depth" },
  { effort: "xhigh", label: "Extra high", description: "Maximum reasoning depth" },
];

function usableModelOptions(options: ProviderModelOption[] | null | undefined): ProviderModelOption[] {
  return Array.isArray(options) ? options.filter((option) => !!option?.model_id) : [];
}

function defaultReasoningForOption(option: ProviderModelOption | null): string {
  if (!option) {
    return "";
  }
  if (option.default_reasoning_effort) {
    return option.default_reasoning_effort;
  }
  return option.supported_reasoning_efforts[0]?.effort || "";
}

function withReasoningFallback(option: ProviderModelOption): ProviderModelOption {
  if (option.supported_reasoning_efforts.length) {
    return option;
  }
  return {
    ...option,
    default_reasoning_effort: option.default_reasoning_effort || "medium",
    supported_reasoning_efforts: FALLBACK_REASONING_OPTIONS,
  };
}

function fallbackModelOption(modelId: string, reasoningEffort: string): ProviderModelOption {
  return {
    model_id: modelId,
    label: modelId,
    description: "Workspace-selected Codex model.",
    default_reasoning_effort: reasoningEffort || "medium",
    supported_reasoning_efforts: FALLBACK_REASONING_OPTIONS,
  };
}

export function ShellDialogs({
  activeDialog,
  onClose,
  onClearRuntimeSessions,
  onLogout,
  onProviderModelSettingsChanged,
  settings,
}: {
  activeDialog: ShellDialog;
  onClose: () => void;
  onClearRuntimeSessions: (sessionIds?: string[]) => Promise<void>;
  onLogout: () => void;
  onProviderModelSettingsChanged: (modelId: string, reasoningEffort: string | null) => Promise<void>;
  settings: PlatformSettings | null;
}) {
  const governance = settings?.workspace.governance || {};
  const provider = settings?.provider.active_provider;
  const modelSettings = settings?.provider.model_settings;
  const selectedModel = modelSettings?.selected_model_id || provider?.default_model_family || "";
  const rawModelOptions = usableModelOptions(modelSettings?.available_models).length
    ? usableModelOptions(modelSettings?.available_models)
    : usableModelOptions(provider?.model_options);
  const modelOptions = (
    rawModelOptions.length
      ? rawModelOptions
      : selectedModel
        ? [fallbackModelOption(selectedModel, modelSettings?.selected_reasoning_effort || "")]
        : []
  ).map(withReasoningFallback);
  const selectedModelSettingsOption = modelOptions.find((option) => option.model_id === selectedModel) || modelOptions[0] || null;
  const selectedReasoning = modelSettings?.selected_reasoning_effort || defaultReasoningForOption(selectedModelSettingsOption);
  const runtimeSessions = settings?.runtime.all_sessions || settings?.runtime.sessions || [];
  const activeRuntimeSessions = runtimeSessions.filter((session) => ACTIVE_RUNTIME_STATUSES.has(session.status));
  const cleanupAllowed = settings?.runtime.cleanup_allowed ?? false;
  const cleanupScope = settings?.runtime.cleanup_scope || "none";
  const [draftModelId, setDraftModelId] = useState(selectedModel);
  const [draftReasoningEffort, setDraftReasoningEffort] = useState(selectedReasoning);
  const [isSavingProvider, setIsSavingProvider] = useState(false);
  const [providerError, setProviderError] = useState<string | null>(null);
  const [cleaningSessionIds, setCleaningSessionIds] = useState<Set<string>>(new Set());
  const [runtimeCleanupError, setRuntimeCleanupError] = useState<string | null>(null);
  const [batchProgress, setBatchProgress] = useState<{ completed: number; total: number; current: string | null } | null>(null);

  useEffect(() => {
    setDraftModelId(selectedModel);
    setDraftReasoningEffort(selectedReasoning);
    setProviderError(null);
  }, [selectedModel, selectedReasoning]);

  const selectedModelOption = useMemo(
    () => modelOptions.find((option) => option.model_id === draftModelId) || modelOptions[0] || null,
    [draftModelId, modelOptions],
  );
  const reasoningOptions = selectedModelOption?.supported_reasoning_efforts || [];
  const canSaveProvider =
    !!provider &&
    !!draftModelId &&
    !isSavingProvider &&
    (draftModelId !== selectedModel || draftReasoningEffort !== selectedReasoning);
  const cleanupScopeLabel =
    cleanupScope === "server"
      ? "Scope: tutto il server"
      : cleanupScope === "workspace"
        ? "Scope: workspace attivo"
        : "Pulizia agent non consentita in questo workspace";

  function handleModelChange(modelId: string) {
    const option = modelOptions.find((item) => item.model_id === modelId) || null;
    setDraftModelId(modelId);
    setDraftReasoningEffort(defaultReasoningForOption(option));
  }

  async function saveProviderSettings() {
    if (!canSaveProvider) {
      return;
    }
    setIsSavingProvider(true);
    setProviderError(null);
    try {
      await onProviderModelSettingsChanged(draftModelId, draftReasoningEffort || null);
    } catch (error) {
      setProviderError(error instanceof Error ? error.message : "Impossibile aggiornare il modello.");
    } finally {
      setIsSavingProvider(false);
    }
  }

  async function clearOneRuntimeSession(sessionId: string) {
    if (!cleanupAllowed || cleaningSessionIds.has(sessionId)) {
      return;
    }
    setRuntimeCleanupError(null);
    setCleaningSessionIds((current) => new Set(current).add(sessionId));
    try {
      await onClearRuntimeSessions([sessionId]);
    } catch (error) {
      setRuntimeCleanupError(error instanceof Error ? error.message : "Impossibile pulire l'agente.");
    } finally {
      setCleaningSessionIds((current) => {
        const next = new Set(current);
        next.delete(sessionId);
        return next;
      });
    }
  }

  async function clearAllRuntimeSessions() {
    if (!cleanupAllowed || !runtimeSessions.length || batchProgress) {
      return;
    }
    setRuntimeCleanupError(null);
    setBatchProgress({ completed: 0, total: runtimeSessions.length, current: "cleanup" });
    try {
      await onClearRuntimeSessions(runtimeSessions.map((session) => session.session_id));
      setBatchProgress({ completed: runtimeSessions.length, total: runtimeSessions.length, current: null });
    } catch (error) {
      setRuntimeCleanupError(error instanceof Error ? error.message : "Impossibile pulire gli agenti.");
    } finally {
      setBatchProgress(null);
    }
  }

  return (
    <>
      <TutorialDialog onClose={onClose} open={activeDialog === "tutorial"} />
      <Dialog
        description="Stato reale letto dalle API core. In default un platform admin pulisce tutto il server; negli altri workspace la pulizia resta locale al workspace attivo."
        onClose={onClose}
        open={activeDialog === "settings"}
        title="Settings"
      >
        <div className="bs-settings-list">
          <Surface>
            <p className="bs-dialog-card__eyebrow">Utente</p>
            <h4 className="bs-dialog-card__title">{settings?.user.display_name || settings?.user.username || "Non disponibile"}</h4>
            <p className="bs-dialog-card__copy">{settings?.user.platform_role || "member"} · {settings?.workspace.name || "Workspace"}</p>
          </Surface>
          <Surface>
            <p className="bs-dialog-card__eyebrow">Provider</p>
            <h4 className="bs-dialog-card__title">{provider?.label || "Provider non caricato"}</h4>
            <p className="bs-dialog-card__copy">
              {selectedModel || "model"} · {selectedReasoning || "reasoning"} · {activeRuntimeSessions.length} attive / {runtimeSessions.length} in scope
            </p>
            <div className="bs-settings-provider-form">
              <label className="bs-settings-field">
                <span>Modello</span>
                <select
                  disabled={!modelOptions.length || isSavingProvider}
                  onChange={(event) => handleModelChange(event.target.value)}
                  value={draftModelId}
                >
                  {modelOptions.map((option) => (
                    <option key={option.model_id} value={option.model_id}>
                      {option.label}
                    </option>
                  ))}
                </select>
              </label>
              <label className="bs-settings-field">
                <span>Reasoning</span>
                <select
                  disabled={!reasoningOptions.length || isSavingProvider}
                  onChange={(event) => setDraftReasoningEffort(event.target.value)}
                  value={draftReasoningEffort}
                >
                  {reasoningOptions.map((option) => (
                    <option key={option.effort} value={option.effort}>
                      {option.label}
                    </option>
                  ))}
                </select>
              </label>
              <Button disabled={!canSaveProvider} loading={isSavingProvider} onClick={saveProviderSettings} size="sm">
                Salva
              </Button>
              {providerError ? <p className="bs-settings-provider-error">{providerError}</p> : null}
            </div>
            <details className="bs-runtime-session-panel">
              <summary>
                <span>Sessioni runtime</span>
                <span>{runtimeSessions.length}</span>
              </summary>
              <div className="bs-runtime-session-toolbar">
                <span className="bs-dialog-card__copy">{cleanupScopeLabel}</span>
                <Button
                  disabled={!cleanupAllowed || !runtimeSessions.length || !!batchProgress}
                  loading={!!batchProgress}
                  onClick={clearAllRuntimeSessions}
                  size="sm"
                  variant="ghost"
                >
                  Pulisci tutte
                </Button>
                {batchProgress ? (
                  <div className="bs-runtime-session-progress" role="status">
                    <progress max={batchProgress.total} value={batchProgress.completed} />
                    <span>
                      {batchProgress.completed}/{batchProgress.total}
                    </span>
                  </div>
                ) : null}
              </div>
              {!cleanupAllowed ? <p className="bs-settings-provider-error">Solo gli admin autorizzati possono pulire gli agenti in questo scope.</p> : null}
              <div className="bs-runtime-session-list">
                {runtimeSessions.length ? runtimeSessions.map((session) => {
                  const isCleaning = cleaningSessionIds.has(session.session_id);
                  return (
                    <div className="bs-runtime-session-row" key={session.session_id}>
                      <div className="bs-runtime-session-main">
                        <strong>{session.agent_id || session.session_id}</strong>
                        <span>{session.workspace_name || session.workspace_id} · {session.effective_mode} · {session.status}</span>
                        <code>{session.session_id}</code>
                      </div>
                      <Button
                        disabled={!cleanupAllowed || !!batchProgress || isCleaning}
                        loading={isCleaning}
                        onClick={() => clearOneRuntimeSession(session.session_id)}
                        size="sm"
                        variant="ghost"
                      >
                        Pulisci
                      </Button>
                    </div>
                  );
                }) : <p className="bs-dialog-card__copy">Nessuna sessione runtime.</p>}
              </div>
              {runtimeCleanupError ? <p className="bs-settings-provider-error">{runtimeCleanupError}</p> : null}
            </details>
          </Surface>
          <Surface>
            <p className="bs-dialog-card__eyebrow">Governance</p>
            <div className="bs-settings-flags">
              {Object.entries(governance).map(([key, value]) => (
                <span className={`bs-settings-flag ${value ? "is-on" : "is-off"}`} key={key}>
                  {key.replaceAll("_", " ")}
                </span>
              ))}
            </div>
          </Surface>
          <button className="bs-settings-logout" onClick={onLogout} type="button">
            Logout
          </button>
        </div>
      </Dialog>
    </>
  );
}

export type { ShellDialog };
