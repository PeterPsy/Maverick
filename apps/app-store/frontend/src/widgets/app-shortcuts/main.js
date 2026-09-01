const list = document.querySelector("#appShortcutList");
const search = document.querySelector("#appShortcutSearch");
const scopeAll = document.querySelector("#appShortcutScopeAll");
const scopePinned = document.querySelector("#appShortcutScopePinned");

const state = {
  activeAppId: "",
  apps: [],
  isLoading: true,
  pinnedIds: [],
  query: "",
  scope: "all",
};

const SHORTCUT_SKELETON_ROWS = 6;

async function requestJson(url, options = {}) {
  const response = await fetch(url, {
    credentials: "same-origin",
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
    ...options,
  });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
    const detail = payload.detail || payload.error || `HTTP ${response.status}`;
    throw new Error(detail);
  }
  return payload;
}

function appIcon(app) {
  if (window.MaverickAppIcons?.renderIcon) {
    return window.MaverickAppIcons.renderIcon(app, "app-shortcuts__icon");
  }
  const frame = document.createElement("span");
  frame.className = "app-shortcuts__icon is-glyph";
  if (frontendRole(app) === "supporting") {
    frame.classList.add("is-supporting-frontend");
  }
  if (!isFrontendLaunchable(app)) {
    frame.classList.add("is-non-launchable");
  }
  frame.setAttribute("aria-hidden", "true");
  const glyph = document.createElement("span");
  glyph.className = "material-symbols-rounded";
  glyph.textContent = "deployed_code";
  frame.append(glyph);
  return frame;
}

function openApp(appId) {
  window.parent?.postMessage({ type: "maverick.widget.open-app", app_id: appId }, "*");
}

function notifyPinnedAppsChanged() {
  window.parent?.postMessage(
    {
      type: "maverick.app.data-changed",
      owner_app_id: "app-store",
      resource: "pinned-apps",
    },
    "*",
  );
}

function isPinned(appId) {
  return state.pinnedIds.includes(appId);
}

function frontendRole(app = {}) {
  if (window.MaverickFrontendPresentation?.frontendRole) {
    return window.MaverickFrontendPresentation.frontendRole(app);
  }
  const role = String(app.frontend_role || app.presentation?.frontend_role || "").trim();
  return ["workspace", "supporting", "none"].includes(role) ? role : "none";
}

function isFrontendLaunchable(app = {}) {
  if (window.MaverickFrontendPresentation?.frontendLaunchable) {
    return window.MaverickFrontendPresentation.frontendLaunchable(app);
  }
  return app.frontend_launchable === true || frontendRole(app) === "workspace";
}

function sortedApps() {
  const pinnedRank = new Map(state.pinnedIds.map((appId, index) => [appId, index]));
  return [...state.apps].sort((left, right) => {
    const leftPinned = pinnedRank.has(left.app_id);
    const rightPinned = pinnedRank.has(right.app_id);
    if (leftPinned && rightPinned) {
      return pinnedRank.get(left.app_id) - pinnedRank.get(right.app_id);
    }
    if (leftPinned !== rightPinned) {
      return leftPinned ? -1 : 1;
    }
    return (left.name || left.app_id).localeCompare(right.name || right.app_id);
  });
}

function visibleApps() {
  const query = state.query.trim().toLowerCase();
  return sortedApps().filter((app) => {
    if (state.scope === "pinned" && !isPinned(app.app_id)) {
      return false;
    }
    if (!query) {
      return true;
    }
    const text = `${app.app_id} ${app.name || ""} ${app.description || ""}`.toLowerCase();
    return text.includes(query);
  });
}

function surfaceLabel(app) {
  if (frontendRole(app) === "workspace") return "Frontend";
  const surfaces = window.MaverickFrontendPresentation?.normalizeSurfaces
    ? window.MaverickFrontendPresentation.normalizeSurfaces(app)
    : app.provides?.flatMap((item) => item.surfaces || []) || [];
  if (surfaces.includes("mcp")) return "MCP";
  if (surfaces.includes("cli")) return "CLI";
  if (surfaces.includes("backend")) return "Backend";
  return app.publisher || "Maverick";
}

function renderEmpty(message) {
  state.isLoading = false;
  list.removeAttribute("aria-busy");
  list.replaceChildren();
  const empty = document.createElement("p");
  empty.className = "app-shortcuts__empty";
  empty.textContent = message;
  list.append(empty);
}

function renderScope() {
  scopeAll.classList.toggle("is-active", state.scope === "all");
  scopePinned.classList.toggle("is-active", state.scope === "pinned");
  scopeAll.setAttribute("aria-selected", state.scope === "all" ? "true" : "false");
  scopePinned.setAttribute("aria-selected", state.scope === "pinned" ? "true" : "false");
}

function skeletonBlock(className, tagName = "span") {
  const node = document.createElement(tagName);
  node.className = className;
  node.setAttribute("aria-hidden", "true");
  return node;
}

function renderSkeleton() {
  renderScope();
  list.replaceChildren();
  list.setAttribute("aria-busy", "true");
  Array.from({ length: SHORTCUT_SKELETON_ROWS }).forEach((_, index) => {
    const row = skeletonBlock("app-shortcuts__row app-shortcuts__row--skeleton", "article");
    const copy = skeletonBlock("app-shortcuts__skeleton-copy");
    copy.append(
      skeletonBlock(`app-shortcuts__skeleton-line app-shortcuts__skeleton-line--${index % 3 === 0 ? "wide" : "title"}`),
      skeletonBlock(`app-shortcuts__skeleton-line app-shortcuts__skeleton-line--${index % 2 === 0 ? "meta" : "short"}`),
    );
    const button = skeletonBlock("app-shortcuts__button app-shortcuts__button--skeleton", "span");
    button.append(skeletonBlock("app-shortcuts__icon app-shortcuts__icon--skeleton"), copy);
    row.append(button, skeletonBlock("app-shortcuts__pin app-shortcuts__pin--skeleton"));
    list.append(row);
  });
}

function render(apps = visibleApps()) {
  renderScope();
  if (state.isLoading) {
    renderSkeleton();
    return;
  }
  list.removeAttribute("aria-busy");
  list.replaceChildren();
  if (!apps.length) {
    const emptyMessage = state.scope === "pinned"
      ? "No pinned apps in this workspace."
      : "No apps available.";
    renderEmpty(emptyMessage);
    return;
  }
  apps.forEach((app) => {
    const launchable = isFrontendLaunchable(app);
    const row = document.createElement("article");
    row.className = "app-shortcuts__row";
    if (state.activeAppId === app.app_id) {
      row.classList.add("is-active");
    }
    if (!launchable) {
      row.classList.add("is-not-pinnable");
    }

    const button = document.createElement("button");
    button.className = "app-shortcuts__button";
    button.type = "button";
    button.setAttribute(
      "aria-label",
      launchable ? `Open ${app.name || app.app_id}` : `${app.name || app.app_id} does not have a launchable frontend`,
    );
    if (state.activeAppId === app.app_id) {
      button.setAttribute("aria-current", "page");
    }
    if (launchable) {
      button.addEventListener("click", () => openApp(app.app_id));
    } else {
      button.disabled = true;
      button.title = "No launchable frontend";
    }

    const copy = document.createElement("span");
    copy.className = "app-shortcuts__copy";
    const label = document.createElement("span");
    label.className = "app-shortcuts__label";
    label.textContent = app.name || app.app_id;
    const meta = document.createElement("span");
    meta.className = "app-shortcuts__meta";
    meta.textContent = surfaceLabel(app);
    copy.append(label, meta);
    button.append(appIcon(app), copy);

    row.append(button);
    if (launchable) {
      const pin = document.createElement("button");
      pin.className = "app-shortcuts__pin";
      pin.type = "button";
      pin.setAttribute("aria-pressed", isPinned(app.app_id) ? "true" : "false");
      pin.setAttribute("aria-label", isPinned(app.app_id) ? `Remove ${app.name || app.app_id} from pinned apps` : `Pin ${app.name || app.app_id}`);
      pin.title = isPinned(app.app_id) ? "Unpin app" : "Pin app";
      const pinIcon = document.createElement("span");
      pinIcon.className = "material-symbols-rounded";
      pinIcon.setAttribute("aria-hidden", "true");
      pinIcon.textContent = isPinned(app.app_id) ? "keep" : "keep_off";
      pin.append(pinIcon);
      pin.addEventListener("click", (event) => {
        event.stopPropagation();
        togglePinnedApp(app).catch((error) => renderEmpty(error.message));
      });
      row.append(pin);
    }
    list.append(row);
  });
}

async function togglePinnedApp(app) {
  if (!isFrontendLaunchable(app)) {
    return;
  }
  const payload = await requestJson("/api/apps/app-store/backend", {
    method: "POST",
    body: JSON.stringify({ action: "pinned_apps.toggle", app_id: app.app_id }),
  });
  state.pinnedIds = payload.state?.pinned_apps || [];
  notifyPinnedAppsChanged();
  render();
}

function applyWidgetContext(payload) {
  const nextActiveAppId = payload?.context?.content?.payload?.active_app_id;
  if (typeof nextActiveAppId === "string") {
    state.activeAppId = nextActiveAppId;
    render();
  }
}

async function load() {
  state.isLoading = true;
  render();
  try {
    const [registry, pinned] = await Promise.all([
      requestJson("/api/apps"),
      requestJson("/api/apps/app-store/backend", {
        method: "POST",
        body: JSON.stringify({ action: "pinned_apps.list" }),
      }),
    ]);
    state.apps = registry.items || [];
    const launchableIds = new Set(state.apps.filter(isFrontendLaunchable).map((app) => app.app_id));
    state.pinnedIds = (pinned.pinned_apps || []).filter((appId) => launchableIds.has(appId));
    state.isLoading = false;
    render();
  } catch (error) {
    state.isLoading = false;
    throw error;
  }
}

search.addEventListener("input", () => {
  state.query = search.value;
  render();
});

scopeAll.addEventListener("click", () => {
  state.scope = "all";
  render();
});

scopePinned.addEventListener("click", () => {
  state.scope = "pinned";
  render();
});

window.addEventListener("message", (event) => {
  if (event.origin !== window.location.origin || !event.data || typeof event.data !== "object") {
    return;
  }
  if (event.data.type === "maverick.widget.context-changed") {
    applyWidgetContext(event.data);
  }
  if (event.data.type === "maverick.widget.data-changed" && event.data.owner_app_id === "app-store") {
    load().catch((error) => renderEmpty(error.message));
  }
});

load().catch((error) => renderEmpty(error.message));
