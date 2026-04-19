import { useState } from "react";
import { ChatProject, ChatThread } from "../../api/client";

export type FloatingPanelPosition = {
  top: number;
  right: number;
};

export type FloatingPanel =
  | { kind: "project"; project: ChatProject; position: FloatingPanelPosition }
  | { kind: "thread"; thread: ChatThread; position: FloatingPanelPosition };

export function SettingsPanel({
  onClose,
  onCreateChat,
  onDeleteProject,
  onDeleteThread,
  onRenameProject,
  onRenameThread,
  panel,
  projects,
}: {
  onClose: () => void;
  onCreateChat: (projectId?: string | null) => Promise<void>;
  onDeleteProject: (projectId: string) => Promise<void>;
  onDeleteThread: (threadId: string) => Promise<void>;
  onRenameProject: (projectId: string, name: string) => Promise<void>;
  onRenameThread: (threadId: string, title: string, projectId: string | null) => Promise<void>;
  panel: FloatingPanel;
  projects: ChatProject[];
}) {
  const initialName = panel.kind === "project" ? panel.project.name : panel.thread.title;
  const [name, setName] = useState(initialName);
  const [projectId, setProjectId] = useState(panel.kind === "thread" ? panel.thread.project_id || "" : "");
  const [isSaving, setIsSaving] = useState(false);
  const [panelError, setPanelError] = useState<string | null>(null);

  async function submit() {
    setIsSaving(true);
    setPanelError(null);
    try {
      if (panel.kind === "project") {
        await onRenameProject(panel.project.project_id, name);
      } else {
        await onRenameThread(panel.thread.thread_id, name, projectId || null);
      }
    } catch (error) {
      setPanelError(error instanceof Error ? error.message : "Unable to save settings.");
    } finally {
      setIsSaving(false);
    }
  }

  async function remove() {
    setIsSaving(true);
    setPanelError(null);
    try {
      if (panel.kind === "project") {
        await onDeleteProject(panel.project.project_id);
      } else {
        await onDeleteThread(panel.thread.thread_id);
      }
    } catch (error) {
      setPanelError(error instanceof Error ? error.message : "Unable to delete item.");
    } finally {
      setIsSaving(false);
    }
  }

  return (
    <div
      className="bs-instance-menu__menu bs-sidebar-floating-panel"
      role="dialog"
      aria-label="Sidebar settings"
      style={{ right: panel.position.right, top: panel.position.top }}
    >
      <div className="bs-sidebar-floating-panel__head">
        <p className="bs-sidebar-floating-panel__eyebrow">{panel.kind === "project" ? "Project settings" : "Chat settings"}</p>
        <button className="bs-sidebar-floating-panel__close" onClick={onClose} type="button">
          ×
        </button>
      </div>
      <label className="bs-sidebar-floating-panel__field">
        <span>Name</span>
        <input autoFocus value={name} onChange={(event) => setName(event.target.value)} />
      </label>
      {panel.kind === "thread" ? (
        <label className="bs-sidebar-floating-panel__field">
          <span>Project</span>
          <select value={projectId} onChange={(event) => setProjectId(event.target.value)}>
            <option value="">Senza progetto</option>
            {projects.map((project) => (
              <option value={project.project_id} key={project.project_id}>
                {project.name}
              </option>
            ))}
          </select>
        </label>
      ) : null}
      {panelError ? <p className="bs-sidebar-floating-panel__error">{panelError}</p> : null}
      <div className="bs-sidebar-floating-panel__actions">
        <button disabled={isSaving || !name.trim()} onClick={submit} type="button">
          Salva
        </button>
        {panel.kind === "project" ? (
          <button disabled={isSaving} onClick={() => onCreateChat(panel.project.project_id)} type="button">
            Nuova chat
          </button>
        ) : null}
        <button className="is-danger" disabled={isSaving} onClick={remove} type="button">
          Elimina
        </button>
      </div>
    </div>
  );
}
