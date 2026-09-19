import type { WorkspaceItem } from "../api";

export function WorkspaceSwitcher({
  activeWorkspaceId,
  isLoading = false,
  onWorkspaceChange,
  workspaces,
}: {
  activeWorkspaceId: string;
  isLoading?: boolean;
  onWorkspaceChange: (workspaceId: string) => Promise<void> | void;
  workspaces: WorkspaceItem[];
}) {
  const hasActiveWorkspace = workspaces.some((workspace) => workspace.workspace_id === activeWorkspaceId);

  async function handleChange(workspaceId: string) {
    if (!workspaceId || workspaceId === activeWorkspaceId) {
      return;
    }
    await onWorkspaceChange(workspaceId);
  }

  if (isLoading) {
    return (
      <div className="bs-workspace-switcher" aria-hidden="true">
        <div className="bs-workspace-switcher__row">
          <div className="bs-workspace-switcher__select-frame bs-workspace-switcher__skeleton-frame">
            <span className="bs-workspace-switcher__skeleton-line" />
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="bs-workspace-switcher">
      <div className="bs-workspace-switcher__row">
        <div className="bs-workspace-switcher__select-frame">
          <span aria-hidden="true" className="material-symbols-rounded bs-workspace-switcher__icon">workspaces</span>
          <select aria-label="Workspace" id="bs-workspace-select" onChange={(event) => handleChange(event.target.value)} value={activeWorkspaceId}>
            {!hasActiveWorkspace ? <option value={activeWorkspaceId}>{activeWorkspaceId}</option> : null}
            {workspaces.map((workspace) => (
              <option key={workspace.workspace_id} value={workspace.workspace_id}>
                {workspace.name || workspace.workspace_id}
              </option>
            ))}
          </select>
          <span aria-hidden="true" className="material-symbols-rounded bs-workspace-switcher__chevron">expand_more</span>
        </div>
      </div>
    </div>
  );
}
