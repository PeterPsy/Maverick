import { loadUsers, type User } from '../../adminApi';
import './styles.css';

const MOBILE_LAYOUT_QUERY = '(max-width: 979px)';

let users: User[] = [];
let query = '';
let selectedUserId = '';
let error = '';
let isInitialLoading = true;

function userLabel(user: User) {
  return user.display_name || user.username;
}

function roleLabel(user: User) {
  return user.platform_role === 'admin' ? 'Admin' : 'Member';
}

function filteredUsers() {
  const needle = query.trim().toLowerCase();
  if (!needle) {
    return users;
  }
  return users.filter((user) => {
    const haystack = `${userLabel(user)} ${user.username} ${user.email || ''} ${user.user_id} ${user.platform_role}`.toLowerCase();
    return haystack.includes(needle);
  });
}

function isMobileLayoutViewport() {
  if (typeof window === 'undefined') {
    return false;
  }
  try {
    const shellWindow = window.parent && window.parent !== window ? window.parent : window;
    return typeof shellWindow.matchMedia === 'function' && shellWindow.matchMedia(MOBILE_LAYOUT_QUERY).matches;
  } catch {
    return typeof window.matchMedia === 'function' && window.matchMedia(MOBILE_LAYOUT_QUERY).matches;
  }
}

function openUserInShell(userId: string) {
  selectedUserId = userId;
  render();
  window.parent?.postMessage(
    {
      type: 'maverick.widget.open-app',
      app_id: 'user-admin',
      params: {
        app_page: `users/${encodeURIComponent(userId)}`,
        user_id: userId
      }
    },
    window.location.origin
  );
  if (isMobileLayoutViewport()) {
    window.parent?.postMessage({ type: 'maverick.shell.sidebar.close' }, window.location.origin);
  }
}

async function refreshUsers() {
  try {
    users = await loadUsers();
    if (!selectedUserId || !users.some((user) => user.user_id === selectedUserId)) {
      selectedUserId = users[0]?.user_id || '';
    }
    error = '';
  } catch (loadError) {
    error = loadError instanceof Error ? loadError.message : 'Unable to load users.';
  } finally {
    isInitialLoading = false;
    render();
  }
}

function handleShellMessage(event: MessageEvent) {
  if (event.origin !== window.location.origin || !event.data || typeof event.data !== 'object') {
    return;
  }
  const payload = event.data as {
    context?: { content?: { payload?: unknown } };
    owner_app_id?: string;
    resource?: string;
    selection?: Record<string, unknown>;
    type?: string;
  };
  if (payload.type === 'maverick.widget.context-changed') {
    const params = activeAppParamsFromContext(payload.context?.content?.payload);
    const userId = userIdFromParams(params);
    if (userId) {
      selectedUserId = userId;
      render();
    }
    return;
  }
  if (payload.type === 'maverick.app.selection-changed' && payload.owner_app_id === 'user-admin') {
    const userId = scalarString(payload.selection?.user_id);
    if (userId) {
      selectedUserId = userId;
      render();
    }
    return;
  }
  if (payload.type === 'maverick.widget.data-changed' && payload.owner_app_id === 'user-admin' && payload.resource === 'users') {
    void refreshUsers();
  }
}

function activeAppParamsFromContext(payload: unknown): Record<string, unknown> {
  if (!payload || typeof payload !== 'object' || Array.isArray(payload)) {
    return {};
  }
  const activeAppParams = (payload as { active_app_params?: unknown }).active_app_params;
  return activeAppParams && typeof activeAppParams === 'object' && !Array.isArray(activeAppParams)
    ? activeAppParams as Record<string, unknown>
    : {};
}

function userIdFromParams(params: Record<string, unknown>) {
  const directUserId = scalarString(params.user_id) || scalarString(params.selected_user_id) || scalarString(params.id);
  if (directUserId) {
    return directUserId;
  }
  const appPage = scalarString(params.app_page);
  const match = /^users\/([^/?#]+)$/.exec(appPage);
  if (!match?.[1]) {
    return '';
  }
  try {
    return decodeURIComponent(match[1]);
  } catch {
    return match[1];
  }
}

function scalarString(value: unknown) {
  return typeof value === 'string' ? value.trim() : '';
}

function escapeHtml(value: string) {
  return value.replace(/[&<>"']/g, (character) => {
    switch (character) {
      case '&':
        return '&amp;';
      case '<':
        return '&lt;';
      case '>':
        return '&gt;';
      case '"':
        return '&quot;';
      default:
        return '&#39;';
    }
  });
}

function render() {
  const root = document.getElementById('user-admin-sidebar-root');
  if (!root) {
    return;
  }
  const rows = filteredUsers();
  root.innerHTML = `<main class="user-admin-sidebar-widget ${isMobileLayoutViewport() ? 'is-shell-mobile' : ''}">
    <div class="user-admin-sidebar-search-frame">
      <span class="material-symbols-rounded" aria-hidden="true">search</span>
      <input
        aria-label="Search users"
        class="user-admin-sidebar-search"
        placeholder="Search users"
        value="${escapeHtml(query)}"
      />
    </div>
    ${error ? `<p class="user-admin-sidebar-empty">${escapeHtml(error)}</p>` : ''}
    <div class="user-admin-sidebar-list">
      ${
        isInitialLoading
          ? sidebarSkeletonHtml()
          : rows.length
            ? rows.map(userRowHtml).join('')
            : '<p class="user-admin-sidebar-empty">No users found.</p>'
      }
    </div>
  </main>`;
  bindEvents();
}

function userRowHtml(user: User) {
  const activeClass = user.user_id === selectedUserId ? 'is-active' : '';
  const status = user.is_active ? 'active' : 'disabled';
  return `<button class="user-admin-sidebar-row ${activeClass}" data-user-id="${escapeHtml(user.user_id)}" type="button">
    <span class="material-symbols-rounded user-admin-sidebar-row__icon" aria-hidden="true">${user.platform_role === 'admin' ? 'admin_panel_settings' : 'account_circle'}</span>
    <span class="user-admin-sidebar-row__copy">
      <strong>${escapeHtml(userLabel(user))}</strong>
      <span>${escapeHtml(roleLabel(user))} · ${user.memberships.length} workspace · ${status}</span>
    </span>
  </button>`;
}

function sidebarSkeletonHtml() {
  return `<div aria-hidden="true" class="user-admin-sidebar-skeleton">
    ${Array.from({ length: 7 }).map(() => `<div class="user-admin-sidebar-skeleton__row">
      <span class="user-admin-sidebar-skeleton__icon"></span>
      <span class="user-admin-sidebar-skeleton__copy"><span></span><span></span></span>
    </div>`).join('')}
  </div>`;
}

function bindEvents() {
  const searchInput = document.querySelector<HTMLInputElement>('.user-admin-sidebar-search');
  searchInput?.addEventListener('input', () => {
    query = searchInput.value;
    render();
  });
  document.querySelectorAll<HTMLButtonElement>('[data-user-id]').forEach((button) => {
    button.addEventListener('click', () => {
      const userId = button.dataset.userId || '';
      if (userId) {
        openUserInShell(userId);
      }
    });
  });
}

function installShellSidebarCloseSwipe() {
  let start: { id: number; x: number; y: number } | null = null;
  document.addEventListener('touchstart', (event) => {
    if (!isMobileLayoutViewport() || event.touches.length !== 1 || swipeIgnoredTarget(event.target)) {
      start = null;
      return;
    }
    const touch = event.touches[0];
    start = { id: touch.identifier, x: touch.clientX, y: touch.clientY };
  }, { passive: true });
  document.addEventListener('touchmove', (event) => {
    if (!start) {
      return;
    }
    const touch = Array.from(event.changedTouches).find((item) => item.identifier === start?.id);
    if (!touch) {
      return;
    }
    const deltaX = touch.clientX - start.x;
    const deltaY = Math.abs(touch.clientY - start.y);
    if (Math.abs(deltaX) > 12 && Math.abs(deltaX) > deltaY) {
      event.preventDefault();
      event.stopPropagation();
    }
    if (deltaX <= -72 && deltaY <= 48) {
      event.preventDefault();
      event.stopPropagation();
      window.parent?.postMessage({ type: 'maverick.shell.sidebar.close' }, window.location.origin);
      start = null;
    }
  }, { passive: false });
  document.addEventListener('touchcancel', () => {
    start = null;
  }, { passive: true });
  document.addEventListener('touchend', () => {
    start = null;
  }, { passive: true });
}

function swipeIgnoredTarget(target: EventTarget | null) {
  return target instanceof Element && Boolean(target.closest('input, textarea, select, [contenteditable="true"], [data-no-sidebar-swipe]'));
}

window.addEventListener('message', handleShellMessage);
installShellSidebarCloseSwipe();
render();
void refreshUsers();
