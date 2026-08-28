import { useEffect, useRef, useState } from "react";
import {
  getSourceAppChatCapabilities,
  getSourceAppChatContext,
  setSourceAppChatDesignSystem,
  type SourceAppChatCapabilities,
  type SourceAppChatContext,
  type SourceAppChatMode,
} from "../api/client";
import { sourceAppPresentation } from "../lib/sourceAppPresentation";

export function SourceAppChatTools({
  disabled,
  mode,
  onOpenSettings,
  onOpenTools,
  onProjectResolved,
  onSelectMode,
  onSelectProject,
  projectId,
  projectSelectionLocked = false,
  sourceAppId,
}: {
  disabled: boolean;
  mode: SourceAppChatMode;
  onOpenSettings?: (section?: "designSystems") => void;
  onOpenTools?: () => void;
  onProjectResolved?: (projectId: string) => void;
  onSelectMode: (mode: SourceAppChatMode) => void;
  onSelectProject?: (projectId: string) => void;
  projectId: string;
  projectSelectionLocked?: boolean;
  sourceAppId: string;
}) {
  const [open, setOpen] = useState(false);
  const [capabilities, setCapabilities] = useState<SourceAppChatCapabilities | null>(null);
  const [context, setContext] = useState<SourceAppChatContext | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const [updating, setUpdating] = useState(false);
  const controlRef = useRef<HTMLDivElement | null>(null);
  const triggerRef = useRef<HTMLButtonElement | null>(null);

  useEffect(() => {
    setCapabilities(null);
    setContext(null);
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
    if (!open || !sourceAppId) {
      return;
    }
    const abortController = new AbortController();
    setLoading(true);
    setError("");
    void Promise.all([
      getSourceAppChatCapabilities(sourceAppId, { signal: abortController.signal }),
      getSourceAppChatContext(sourceAppId, projectId, { signal: abortController.signal }),
    ])
      .then(([nextCapabilities, nextContext]) => {
        setCapabilities(nextCapabilities);
        setContext(nextContext);
        const resolvedProjectId = nextContext.project?.id || "";
        if (!projectId && resolvedProjectId) {
          onProjectResolved?.(resolvedProjectId);
        }
      })
      .catch((loadError) => {
        if (!abortController.signal.aborted) {
          setError(loadError instanceof Error ? loadError.message : "Design Studio options are unavailable.");
        }
      })
      .finally(() => {
        if (!abortController.signal.aborted) {
          setLoading(false);
        }
      });
    return () => abortController.abort();
  }, [onProjectResolved, open, projectId, sourceAppId]);

  const presentation = sourceAppPresentation(sourceAppId);
  const modes = capabilities?.modes || [];
  const effectiveProjectId = projectId || context?.project?.id || "";
  const selectedProject = context?.projects.find((project) => project.id === effectiveProjectId)
    || context?.project
    || null;
  const projectStatus = selectedProject
    ? projectSelectionLocked
      ? "Bound to conversation"
      : context?.selection_source === "automatic" && !projectId
        ? "Selected automatically"
        : "Synced with workspace"
    : "No project selected";

  async function selectDesignSystem(designSystemId: string) {
    if (!effectiveProjectId || updating) {
      return;
    }
    setUpdating(true);
    setError("");
    try {
      const result = await setSourceAppChatDesignSystem({
        designSystemId: designSystemId || null,
        projectId: effectiveProjectId,
        sourceAppId,
      });
      setContext((current) => current ? {
        ...current,
        od_project_id: result.od_project_id,
        project: result.project,
        projects: current.projects.map((project) => (
          project.id === result.project.id ? result.project : project
        )),
      } : current);
    } catch (updateError) {
      setError(updateError instanceof Error ? updateError.message : "The design system could not be updated.");
    } finally {
      setUpdating(false);
    }
  }

  function openNativeSurface(action: () => void) {
    setOpen(false);
    action();
  }

  return (
    <div className="chatapp-source-tools" ref={controlRef}>
      <button
        aria-expanded={open}
        aria-haspopup="dialog"
        aria-label="Design Studio"
        className={`chatapp-composer__tool-button chatapp-source-tools__button ${open ? "is-active" : ""}`}
        disabled={disabled}
        onClick={() => setOpen((current) => !current)}
        ref={triggerRef}
        title="Design Studio"
        type="button"
      >
        <span aria-hidden="true" className="material-symbols-rounded">{presentation?.icon || "design_services"}</span>
      </button>
      {open ? (
        <div aria-label="Design Studio options" className="chatapp-source-tools__menu" role="dialog">
          <div className="chatapp-source-tools__header">
            <span className="chatapp-source-tools__identity">
              <span aria-hidden="true" className="material-symbols-rounded">design_services</span>
              <span>
                <strong>Design Studio</strong>
                <small>{capabilities?.label || presentation?.label || "OpenDesign"}</small>
              </span>
            </span>
            <span className={selectedProject ? "is-connected" : ""}>{projectStatus}</span>
          </div>

          <label className="chatapp-source-tools__field">
            <span>Project</span>
            <select
              aria-label="Design Studio project"
              disabled={loading || updating || projectSelectionLocked || !context?.projects.length}
              onChange={(event) => {
                const nextProjectId = event.currentTarget.value;
                const nextProject = context?.projects.find((project) => project.id === nextProjectId) || null;
                if (!nextProject || nextProjectId === effectiveProjectId) {
                  return;
                }
                setContext((current) => current ? {
                  ...current,
                  od_project_id: nextProjectId,
                  project: nextProject,
                  selection_source: "workspace",
                } : current);
                onSelectProject?.(nextProjectId);
              }}
              value={effectiveProjectId}
            >
              {!effectiveProjectId ? <option value="">Select a project</option> : null}
              {(context?.projects || []).map((project) => (
                <option key={project.id} value={project.id}>{project.name}</option>
              ))}
            </select>
            {projectSelectionLocked ? <small>This conversation stays bound to its original project.</small> : null}
          </label>

          <label className="chatapp-source-tools__field">
            <span>Design system</span>
            <select
              aria-label="Design system"
              disabled={loading || updating || !selectedProject}
              onChange={(event) => void selectDesignSystem(event.currentTarget.value)}
              value={selectedProject?.design_system_id || ""}
            >
              <option value="">No design system</option>
              {(context?.design_systems || []).map((designSystem) => (
                <option
                  disabled={designSystem.status !== "published"}
                  key={designSystem.id}
                  value={designSystem.id}
                >
                  {designSystem.title}{designSystem.status !== "published" ? ` (${designSystem.status || "unavailable"})` : ""}
                </option>
              ))}
            </select>
          </label>

          {modes.length ? (
            <>
              <div className="chatapp-source-tools__section-label">Mode</div>
              <div className="chatapp-source-tools__modes">
                {modes.map((item) => (
                  <button
                    aria-checked={mode === item}
                    className="chatapp-source-tools__mode"
                    key={item}
                    onClick={() => onSelectMode(item)}
                    role="radio"
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

          {onOpenSettings || onOpenTools ? (
            <>
              <div className="chatapp-source-tools__section-label">OpenDesign</div>
              <div className="chatapp-source-tools__list">
                {onOpenSettings ? (
                  <button
                    className="chatapp-source-tools__item"
                    onClick={() => openNativeSurface(() => onOpenSettings("designSystems"))}
                    type="button"
                  >
                    <span aria-hidden="true" className="material-symbols-rounded">palette</span>
                    <span>Design system settings<small>Create, edit and manage OpenDesign systems.</small></span>
                  </button>
                ) : null}
                {onOpenTools ? (
                  <button
                    className="chatapp-source-tools__item"
                    onClick={() => openNativeSurface(onOpenTools)}
                    type="button"
                  >
                    <span aria-hidden="true" className="material-symbols-rounded">draw</span>
                    <span>Workspace tools<small>Open the native sketch and canvas tools.</small></span>
                  </button>
                ) : null}
                {onOpenSettings ? (
                  <button
                    className="chatapp-source-tools__item"
                    onClick={() => openNativeSurface(() => onOpenSettings())}
                    type="button"
                  >
                    <span aria-hidden="true" className="material-symbols-rounded">settings</span>
                    <span>OpenDesign settings<small>Access the remaining native OpenDesign preferences.</small></span>
                  </button>
                ) : null}
              </div>
            </>
          ) : null}

          {error ? <p className="chatapp-source-tools__error" role="alert">{error}</p> : null}
          {loading ? <p className="chatapp-source-tools__status">Loading Design Studio context…</p> : null}
          {updating ? <p className="chatapp-source-tools__status">Updating design system…</p> : null}
        </div>
      ) : null}
    </div>
  );
}

function modeLabel(mode: SourceAppChatMode): string {
  return mode === "chat" ? "Chat" : mode === "plan" ? "Plan" : "Design";
}
