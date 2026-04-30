import { createWorkspace, switchWorkspace, WorkspaceItem } from "../api";

export function WorkspaceSwitcher({
  activeWorkspaceId,
  canCreateWorkspace,
  onChanged,
  workspaces,
}: {
  activeWorkspaceId: string;
  canCreateWorkspace: boolean;
  onChanged: () => void;
  workspaces: WorkspaceItem[];
}) {
  async function handleChange(workspaceId: string) {
    if (!workspaceId || workspaceId === activeWorkspaceId) {
      return;
    }
    await switchWorkspace(workspaceId);
    onChanged();
  }

  async function handleCreate() {
    const name = window.prompt("Nome del nuovo workspace");
    if (!name?.trim()) {
      return;
    }
    await createWorkspace(name.trim());
    onChanged();
  }

  return (
    <div className="bs-workspace-switcher">
      <div className="bs-workspace-switcher__row">
        <div className="bs-workspace-switcher__select-frame">
          <span aria-hidden="true" className="material-symbols-rounded bs-workspace-switcher__icon">workspaces</span>
          <select aria-label="Workspace" id="bs-workspace-select" onChange={(event) => handleChange(event.target.value)} value={activeWorkspaceId}>
            {workspaces.map((workspace) => (
              <option key={workspace.workspace_id} value={workspace.workspace_id}>
                {workspace.name || workspace.workspace_id}
              </option>
            ))}
          </select>
          <span aria-hidden="true" className="material-symbols-rounded bs-workspace-switcher__chevron">expand_more</span>
        </div>
        {canCreateWorkspace ? (
          <button aria-label="Crea workspace" className="bs-workspace-switcher__create" onClick={handleCreate} type="button">
            <span aria-hidden="true" className="material-symbols-rounded">add</span>
          </button>
        ) : null}
      </div>
    </div>
  );
}
