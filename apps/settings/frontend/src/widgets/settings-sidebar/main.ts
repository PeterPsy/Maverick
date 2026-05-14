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
let selectedPageId: SettingsPageId = initialPageId();

function initialPageId(): SettingsPageId {
  return settingsPageIdFromParams(Object.fromEntries(new URLSearchParams(window.location.search).entries())) || DEFAULT_SETTINGS_PAGE_ID;
}

function filteredPages() {
  const needle = query.trim().toLowerCase();
  if (!needle) {
    return SETTINGS_PAGES;
  }
  return SETTINGS_PAGES.filter((page) => `${page.title} ${page.summary} ${page.id}`.toLowerCase().includes(needle));
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

function openPageInShell(pageId: SettingsPageId) {
  selectedPageId = pageId;
  render();
  window.parent?.postMessage(
    {
      type: 'maverick.widget.open-app',
      app_id: 'settings',
      params: {
        app_page: settingsAppPageFor(pageId),
        page_id: pageId
      }
    },
    window.location.origin
  );
  if (isMobileLayoutViewport()) {
    window.parent?.postMessage({ type: 'maverick.shell.sidebar.close' }, window.location.origin);
  }
}

function handleShellMessage(event: MessageEvent) {
  if (event.origin !== window.location.origin || !event.data || typeof event.data !== 'object') {
    return;
  }
  const payload = event.data as {
    context?: { content?: { payload?: unknown } };
    owner_app_id?: string;
    selection?: Record<string, unknown>;
    type?: string;
  };
  if (payload.type === 'maverick.widget.context-changed') {
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
  root.innerHTML = `<main class="settings-sidebar-widget ${isMobileLayoutViewport() ? 'is-shell-mobile' : ''}">
    <div class="settings-sidebar-search-frame">
      <span class="material-symbols-rounded" aria-hidden="true">search</span>
      <input
        aria-label="Search settings pages"
        class="settings-sidebar-search"
        placeholder="Search pages"
        value="${escapeAttr(query)}"
      />
    </div>
    <div class="settings-sidebar-list">
      ${pages.length ? pages.map(pageRowHtml).join('') : '<p class="settings-sidebar-empty">No pages found.</p>'}
    </div>
  </main>`;
  bindEvents();
}

function pageRowHtml(page: SettingsPage) {
  const activeClass = page.id === selectedPageId ? 'is-active' : '';
  return `<button class="settings-sidebar-row ${activeClass}" data-page-id="${escapeAttr(page.id)}" type="button">
    <span class="material-symbols-rounded settings-sidebar-row__icon" aria-hidden="true">${escapeHtml(page.icon)}</span>
    <span class="settings-sidebar-row__copy">
      <strong>${escapeHtml(page.title)}</strong>
      <span>${escapeHtml(page.summary)}</span>
    </span>
  </button>`;
}

function bindEvents() {
  const searchInput = document.querySelector<HTMLInputElement>('.settings-sidebar-search');
  searchInput?.addEventListener('input', () => {
    query = searchInput.value;
    render();
  });
  document.querySelectorAll<HTMLButtonElement>('[data-page-id]').forEach((button) => {
    button.addEventListener('click', () => {
      const pageId = settingsPageIdFromParams({ page_id: button.dataset.pageId || '' });
      if (pageId) {
        openPageInShell(pageId);
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
