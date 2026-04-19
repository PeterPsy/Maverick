import { createWorkspace, switchWorkspace, WorkspaceItem } from "../api";

export function WorkspaceSwitcher({
  activeWorkspaceId,
  onChanged,
  workspaces,
}: {
  activeWorkspaceId: string;
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
      <label className="bs-workspace-switcher__label" htmlFor="bs-workspace-select">
        Workspace
      </label>
      <div className="bs-workspace-switcher__row">
        <select id="bs-workspace-select" onChange={(event) => handleChange(event.target.value)} value={activeWorkspaceId}>
          {workspaces.map((workspace) => (
            <option key={workspace.workspace_id} value={workspace.workspace_id}>
              {workspace.name || workspace.workspace_id}
            </option>
          ))}
        </select>
        <button aria-label="Crea workspace" className="bs-workspace-switcher__create" onClick={handleCreate} type="button">
          <span aria-hidden="true" className="material-symbols-rounded">add</span>
        </button>
      </div>
    </div>
  );
}
