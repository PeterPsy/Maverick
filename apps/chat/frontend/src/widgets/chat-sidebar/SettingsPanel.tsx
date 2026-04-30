import { useState } from "react";
import { ChatProject } from "../../api/client";

export type FloatingPanelPosition = {
  top: number;
  right: number;
};

export type FloatingPanel = { kind: "project"; project: ChatProject; position: FloatingPanelPosition };

export function SettingsPanel({
  onClose,
  onCreateChat,
  onDeleteProject,
  onRenameProject,
  panel,
}: {
  onClose: () => void;
  onCreateChat: (projectId?: string | null) => Promise<void>;
  onDeleteProject: (projectId: string) => Promise<void>;
  onRenameProject: (projectId: string, name: string) => Promise<void>;
  panel: FloatingPanel;
}) {
  const [name, setName] = useState(panel.project.name);
  const [isSaving, setIsSaving] = useState(false);
  const [panelError, setPanelError] = useState<string | null>(null);

  async function submit() {
    setIsSaving(true);
    setPanelError(null);
    try {
      await onRenameProject(panel.project.project_id, name);
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
      await onDeleteProject(panel.project.project_id);
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
        <p className="bs-sidebar-floating-panel__eyebrow">Project settings</p>
        <button className="bs-sidebar-floating-panel__close" onClick={onClose} type="button">
          <span aria-hidden="true" className="material-symbols-rounded">close</span>
        </button>
      </div>
      <label className="bs-sidebar-floating-panel__field">
        <span>Name</span>
        <input autoFocus value={name} onChange={(event) => setName(event.target.value)} />
      </label>
      {panelError ? <p className="bs-sidebar-floating-panel__error">{panelError}</p> : null}
      <div className="bs-sidebar-floating-panel__actions">
        <button disabled={isSaving || !name.trim()} onClick={submit} type="button">
          Salva
        </button>
        <button disabled={isSaving} onClick={() => onCreateChat(panel.project.project_id)} type="button">
          Nuova chat
        </button>
        <button className="is-danger" disabled={isSaving} onClick={remove} type="button">
          Elimina
        </button>
      </div>
    </div>
  );
}
