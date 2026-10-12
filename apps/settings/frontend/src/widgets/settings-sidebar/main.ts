import { applySettingsTheme } from '../../settingsTheme';
import { isExactMaverickParentMessage } from '@maverick/pwa-cache';
import {
  DEFAULT_SETTINGS_PAGE_ID,
  SETTINGS_PAGES,
  settingsAppPageFor,
  settingsPageIdFromParams,
  type SettingsPage,
  type SettingsPageId
} from '../../pages';
import './styles.css';

const MOBILE_LAYOUT_QUERY = '(max-width: 979px)';

let query = '';
let workspaceId = '';
let selectedPageId: SettingsPageId = initialPageId();

function initialPageId(): SettingsPageId {
  return settingsPageIdFromParams(Object.fromEntries(new URLSearchParams(window.location.search).entries())) || DEFAULT_SETTINGS_PAGE_ID;
}

function filteredPages() {
  const needle = query.trim().toLowerCase();
  if (!needle) {
    return SETTINGS_PAGES.filter(page => page.id !== 'workspace-access');
  }
  return SETTINGS_PAGES.filter((page) => `${page.title} ${page.summary} ${page.id} ${page.keywords}`.toLowerCase().includes(needle));
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

function openPageInShell(pageId: SettingsPageId, setting = '') {
  selectedPageId = pageId;
  render();
  window.parent?.postMessage(
    {
      type: 'maverick.widget.open-app',
      app_id: 'settings',
      params: {
        app_page: settingsAppPageFor(pageId),
        page_id: pageId,
        ...(setting ? { setting } : {})
      }
    },
    "*"
  );
  if (isMobileLayoutViewport()) {
    window.parent?.postMessage({ type: 'maverick.shell.sidebar.close' }, "*");
  }
}

function handleShellMessage(event: MessageEvent) {
  if (!isExactMaverickParentMessage(event) || !event.data || typeof event.data !== 'object') {
    return;
  }
  const payload = event.data as {
    context?: { workspace_id?: string; content?: { payload?: unknown; shell_theme?: unknown } };
    theme?: unknown;
    owner_app_id?: string;
    selection?: Record<string, unknown>;
    type?: string;
  };
  if (payload.type === 'maverick.shell.theme-changed') { applySettingsTheme(payload.theme); return; }
  if (payload.type === 'maverick.widget.context-changed') {
    applySettingsTheme(payload.context?.content?.shell_theme);
    if (payload.context?.workspace_id && payload.context.workspace_id !== workspaceId) {
      workspaceId = payload.context.workspace_id; query = '';
      const search = document.querySelector<HTMLInputElement>('.settings-sidebar-search');
      if (search) search.value = '';
    }
    const pageId = settingsPageIdFromParams(activeAppParamsFromContext(payload.context?.content?.payload));
    if (pageId) {
      selectedPageId = pageId;
      render();
    }
    return;
  }
  if (payload.type === 'maverick.app.selection-changed' && payload.owner_app_id === 'settings') {
    const pageId = settingsPageIdFromParams(payload.selection || {});
    if (pageId) {
      selectedPageId = pageId;
      render();
    }
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

function escapeAttr(value: string) {
  return escapeHtml(value);
}

function render() {
  const root = document.getElementById('settings-sidebar-root');
  if (!root) {
    return;
  }
  const pages = filteredPages();
  if (!root.querySelector('.settings-sidebar-search')) {
    root.innerHTML = `<main class="settings-sidebar-widget"><div class="settings-sidebar-search-frame">
      <span class="material-symbols-rounded" aria-hidden="true">search</span>
      <input aria-label="Search settings" class="settings-sidebar-search" placeholder="Search settings" /></div>
      <nav class="settings-sidebar-list" aria-label="Settings sections"></nav></main>`;
  }
  root.querySelector('.settings-sidebar-widget')?.classList.toggle('is-shell-mobile', isMobileLayoutViewport());
  const list = root.querySelector<HTMLElement>('.settings-sidebar-list');
  if (list) list.innerHTML = pages.length ? ['AI', 'Workspace', 'System'].map(group => {
    const grouped = pages.filter(page => page.group === group).sort((a, b) => a.id === 'models' ? -1 : b.id === 'models' ? 1 : 0);
    return grouped.length ? `<div class="settings-sidebar-group"><h2>${group}</h2>${grouped.map(pageRowHtml).join('')}</div>` : '';
  }).join('') : '<p class="settings-sidebar-empty">No settings found.</p>';
  bindEvents();
}

function pageRowHtml(page: SettingsPage) {
  const activeClass = page.id === selectedPageId ? 'is-active' : '';
  return `<button class="settings-sidebar-row ${activeClass}" data-page-id="${escapeAttr(page.id)}" aria-current="${page.id === selectedPageId ? 'page' : 'false'}" type="button">
    <span class="material-symbols-rounded settings-sidebar-row__icon" aria-hidden="true">${escapeHtml(page.icon)}</span>
    <span class="settings-sidebar-row__copy">
      <strong>${escapeHtml(page.title)}</strong>
      <span>${escapeHtml(page.summary)}</span>
    </span>
  </button>`;
}

function bindEvents() {
  const searchInput = document.querySelector<HTMLInputElement>('.settings-sidebar-search');
  if (searchInput) searchInput.oninput = () => {
    query = searchInput.value;
    render();
  };
  document.querySelectorAll<HTMLButtonElement>('[data-page-id]').forEach((button) => {
    button.addEventListener('click', () => {
      const pageId = settingsPageIdFromParams({ page_id: button.dataset.pageId || '' });
      if (pageId) {
        const needle = query.toLowerCase();
        const setting = pageId === 'models' && /default|model/.test(needle) ? 'default-model'
          : pageId === 'voice' ? 'voice' : pageId === 'users' && /password/.test(needle) ? 'password'
            : pageId === 'cache' ? 'cache' : pageId === 'computer-use' ? 'computer-use' : '';
        openPageInShell(pageId, setting);
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
      window.parent?.postMessage({ type: 'maverick.shell.sidebar.close' }, "*");
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
