import { requestJson, type User, type WorkspaceApp } from './adminApi';

export function createAdminUser(payload: {
  display_name: string;
  email: string;
  password: string;
  platform_role: string;
  username: string;
}): Promise<User> {
  return requestJson<User>('/api/admin/users', {
    method: 'POST',
    body: JSON.stringify(payload)
  });
}

export function updateAdminUser(
  userId: string,
  payload: {
    account_type: string;
    display_name: string;
    email: string;
    is_active: boolean;
    platform_role: string;
  }
): Promise<User> {
  return requestJson<User>(`/api/admin/users/${encodeURIComponent(userId)}`, {
    method: 'PATCH',
    body: JSON.stringify(payload)
  });
}

export function resetAdminUserPassword(userId: string, password: string): Promise<{ status: string }> {
  return requestJson<{ status: string }>(`/api/admin/users/${encodeURIComponent(userId)}/password`, {
    method: 'POST',
    body: JSON.stringify({ password })
  });
}

export function deleteAdminUser(userId: string): Promise<{ status: string }> {
  return requestJson<{ status: string }>(`/api/admin/users/${encodeURIComponent(userId)}`, {
    method: 'DELETE'
  });
}

export function updateAdminUserMemberships(
  userId: string,
  memberships: Array<{ role: string; workspace_id: string }>
): Promise<User> {
  return requestJson<User>(`/api/admin/users/${encodeURIComponent(userId)}/workspaces`, {
    method: 'PUT',
    body: JSON.stringify({ memberships })
  });
}

export function installWorkspaceApp(app: WorkspaceApp): Promise<unknown> {
  return requestJson(`/api/admin/workspace-apps/${encodeURIComponent(app.workspace_id)}/${encodeURIComponent(app.app_id)}`, {
    method: 'POST',
    body: JSON.stringify({ source_id: app.source_id, enabled: true })
  });
}

export function setWorkspaceAppEnabled(app: WorkspaceApp, enabled: boolean): Promise<unknown> {
  return requestJson(`/api/admin/workspace-apps/${encodeURIComponent(app.workspace_id)}/${encodeURIComponent(app.app_id)}`, {
    method: 'PATCH',
    body: JSON.stringify({ status: enabled ? 'enabled' : 'disabled' })
  });
}

export function uninstallWorkspaceApp(app: WorkspaceApp): Promise<unknown> {
  return requestJson(`/api/admin/workspace-apps/${encodeURIComponent(app.workspace_id)}/${encodeURIComponent(app.app_id)}`, {
    method: 'DELETE',
    body: JSON.stringify({})
  });
}
