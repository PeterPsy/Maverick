import type { User, Workspace } from './adminApi';
import { escapeAttr, escapeHtml } from './html';
import { bouncyToggleHtml } from './bouncyToggle';

export function usersPageHtml({
  pendingDeleteUserId,
  selectedUser,
  users,
}: {
  pendingDeleteUserId: string;
  selectedUser: User | undefined;
  users: User[];
}) {
  return `<form class="settings-card settings-create" id="create-user">
      <div>
        <p class="settings-kicker">New user</p>
        <h2>Create access</h2>
      </div>
      <input name="username" placeholder="username" required />
      <input name="password" type="password" placeholder="temporary password" required />
      <input name="display_name" placeholder="display name" />
      <input name="email" type="email" placeholder="email" />
      <select name="platform_role">
        <option value="member">Member</option>
        <option value="admin">Admin</option>
      </select>
      <button type="submit">
        <span class="material-symbols-rounded" aria-hidden="true">person_add</span>
        Create user
      </button>
    </form>
    ${userPickerHtml(users, selectedUser)}
    ${
      selectedUser
        ? `<div class="settings-profile-row">
          <form class="settings-card settings-detail" id="edit-user">
            <div class="settings-heading">
              <div>
                <p class="settings-kicker">Selected user</p>
                <h2>${escapeHtml(selectedUser.display_name || selectedUser.username)}</h2>
              </div>
              <span class="settings-pill">${selectedUser.is_active ? 'active' : 'disabled'}</span>
            </div>
            <div class="settings-grid">
              <label>Name<input name="display_name" value="${escapeAttr(selectedUser.display_name || '')}" /></label>
              <label>Email<input name="email" type="email" value="${escapeAttr(selectedUser.email || '')}" /></label>
              <label>Platform role<select name="platform_role">
                <option value="member" ${selectedUser.platform_role === 'member' ? 'selected' : ''}>Member</option>
                <option value="admin" ${selectedUser.platform_role === 'admin' ? 'selected' : ''}>Admin</option>
              </select></label>
              <label>Account type<select name="account_type">
                <option value="standard" ${selectedUser.account_type === 'standard' ? 'selected' : ''}>Standard</option>
                <option value="facilitated" ${selectedUser.account_type === 'facilitated' ? 'selected' : ''}>Facilitated</option>
              </select></label>
            </div>
            ${bouncyToggleHtml(`<input name="is_active" type="checkbox" role="switch" ${selectedUser.is_active ? 'checked' : ''} />`, 'Account active')}
            <button type="submit">
              <span class="material-symbols-rounded" aria-hidden="true">save</span>
              Save user
            </button>
          </form>
          <form class="settings-card settings-password" id="reset-password">
            <div class="settings-heading">
              <div>
                <p class="settings-kicker">Password</p>
                <h2>Reset access</h2>
              </div>
              <span class="settings-password-icon material-symbols-rounded" aria-hidden="true">key</span>
            </div>
            <p class="settings-card-copy">Set a new temporary password for the selected user.</p>
            <div class="settings-password-grid">
              <label>New password<input name="password" type="password" minlength="8" autocomplete="new-password" required /></label>
              <label>Confirm password<input name="password_confirmation" type="password" minlength="8" autocomplete="new-password" required /></label>
            </div>
            <button type="submit" class="settings-secondary">
              <span class="material-symbols-rounded" aria-hidden="true">password</span>
              Update password
            </button>
            <button type="button" class="settings-danger" id="delete-user">
              <span class="material-symbols-rounded" aria-hidden="true">person_remove</span>
              ${pendingDeleteUserId === selectedUser.user_id ? 'Confirm delete' : 'Delete user'}
            </button>
          </form>
        </div>`
        : '<section class="settings-card"><h2>No users</h2></section>'
    }`;
}

export function workspaceAccessPageHtml({
  selectedUser,
  users,
  workspaces,
}: {
  selectedUser: User | undefined;
  users: User[];
  workspaces: Workspace[];
}) {
  return `${userPickerHtml(users, selectedUser)}
    ${
      selectedUser
        ? `<section class="settings-card">
          <div class="settings-heading">
            <div>
              <p class="settings-kicker">Workspace</p>
              <h2>Assignments</h2>
            </div>
            <button type="button" id="save-memberships">
              <span class="material-symbols-rounded" aria-hidden="true">admin_panel_settings</span>
              Save access
            </button>
          </div>
          <div class="settings-memberships">${membershipHtml(selectedUser, workspaces)}</div>
        </section>`
        : '<section class="settings-card"><h2>No users</h2></section>'
    }`;
}

function userPickerHtml(users: User[], user: User | undefined) {
  if (!users.length) {
    return `<section class="settings-card settings-user-picker">
      <div>
        <p class="settings-kicker">User directory</p>
        <h2>No users</h2>
      </div>
      <p class="settings-card-copy">Create a user before editing profile or workspace access settings.</p>
    </section>`;
  }
  return `<section class="settings-card settings-user-picker">
    <div>
      <p class="settings-kicker">User directory</p>
      <h2>${escapeHtml(user ? user.display_name || user.username : 'Select user')}</h2>
      <p class="settings-card-copy">${users.length} user${users.length === 1 ? '' : 's'} available.</p>
    </div>
    <label class="settings-platform-field">
      <span>Selected user</span>
      <select id="selected-user">
        ${users
          .map((item) => `<option value="${escapeAttr(item.user_id)}" ${item.user_id === user?.user_id ? 'selected' : ''}>${escapeHtml(item.display_name || item.username)} (${escapeHtml(item.username)})</option>`)
          .join('')}
      </select>
    </label>
  </section>`;
}

function membershipHtml(user: User, workspaces: Workspace[]) {
  return workspaces
    .map((workspace) => {
      const membership = user.memberships.find((item) => item.workspace_id === workspace.workspace_id);
      return `<label class="settings-membership">
        <input type="checkbox" data-workspace-enabled="${escapeAttr(workspace.workspace_id)}" ${membership ? 'checked' : ''} />
        <span class="settings-membership-icon material-symbols-rounded" aria-hidden="true">workspaces</span>
        <span>
          <strong>${escapeHtml(workspace.name)}</strong>
          <small>${escapeHtml(workspace.workspace_id)}</small>
        </span>
        <select data-workspace-role="${escapeAttr(workspace.workspace_id)}">
          <option value="member" ${membership?.role !== 'admin' ? 'selected' : ''}>Member</option>
          <option value="admin" ${membership?.role === 'admin' ? 'selected' : ''}>Workspace admin</option>
        </select>
      </label>`;
    })
    .join('');
}
