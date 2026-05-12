const list = document.querySelector("#appShortcutList");
const search = document.querySelector("#appShortcutSearch");
const scopeAll = document.querySelector("#appShortcutScopeAll");
const scopePinned = document.querySelector("#appShortcutScopePinned");

const state = {
  activeAppId: "",
  apps: [],
  pinnedIds: [],
  query: "",
  scope: "all",
};

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
  const frame = document.createElement("span");
  frame.className = "app-shortcuts__icon";
  frame.setAttribute("aria-hidden", "true");
  if (app.logo?.kind === "image" && app.logo.value) {
    const image = document.createElement("img");
    image.alt = "";
    image.loading = "lazy";
    image.src = app.logo.value;
    frame.classList.add("is-image");
    frame.append(image);
    return frame;
  }
  const glyph = document.createElement("span");
  glyph.className = "material-symbols-rounded";
  glyph.textContent = app.logo?.kind === "glyph" && app.logo.value ? app.logo.value : iconName(app);
  frame.classList.add("is-glyph");
  frame.append(glyph);
  return frame;
}

function iconName(app) {
  const icons = {
    "app-store": "storefront",
    agents: "psychology",
    "base-shell": "dashboard",
    checklist: "checklist",
    chat: "chat",
    "developer-kit": "sdk",
    "document-generator": "description",
    "docs-studio": "article",
    "dynamic-views": "dashboard_customize",
    fleet: "table_chart",
    gallery: "photo_library",
    storage: "cloud",
    memory: "neurology",
    skills: "school",
    "user-admin": "admin_panel_settings",
  };
  if (icons[app.app_id]) {
    return icons[app.app_id];
  }
  if ((app.views || []).includes("chat")) {
    return "forum";
  }
  if ((app.views || []).includes("agents")) {
    return "smart_toy";
  }
  if ((app.views || []).includes("shell")) {
    return "dashboard";
  }
  return "deployed_code";
}

function openApp(appId) {
  window.parent?.postMessage({ type: "maverick.widget.open-app", app_id: appId }, window.location.origin);
}

function notifyPinnedAppsChanged() {
  window.parent?.postMessage(
    {
      type: "maverick.app.data-changed",
      owner_app_id: "app-store",
      resource: "pinned-apps",
    },
    window.location.origin,
  );
}

function isPinned(appId) {
  return state.pinnedIds.includes(appId);
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
  const surfaces = app.provides?.flatMap((item) => item.surfaces || []) || [];
  if (surfaces.includes("frontend")) return "Frontend";
  if (surfaces.includes("mcp")) return "MCP";
  if (surfaces.includes("cli")) return "CLI";
  if (surfaces.includes("backend")) return "Backend";
  return app.publisher || "Maverick";
}

function renderEmpty(message) {
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

function render(apps = visibleApps()) {
  renderScope();
  list.replaceChildren();
  if (!apps.length) {
    const emptyMessage = state.scope === "pinned"
      ? "Nessuna app fissata in questo workspace."
      : "Nessuna app disponibile.";
    renderEmpty(emptyMessage);
    return;
  }
  apps.forEach((app) => {
    const row = document.createElement("article");
    row.className = "app-shortcuts__row";
    if (state.activeAppId === app.app_id) {
      row.classList.add("is-active");
    }

    const button = document.createElement("button");
    button.className = "app-shortcuts__button";
    button.type = "button";
    button.setAttribute("aria-label", `Apri ${app.name || app.app_id}`);
    if (state.activeAppId === app.app_id) {
      button.setAttribute("aria-current", "page");
    }
    button.addEventListener("click", () => openApp(app.app_id));

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

    const pin = document.createElement("button");
    pin.className = "app-shortcuts__pin";
    pin.type = "button";
    pin.setAttribute("aria-pressed", isPinned(app.app_id) ? "true" : "false");
    pin.setAttribute("aria-label", isPinned(app.app_id) ? `Rimuovi ${app.name || app.app_id} dalle app fissate` : `Fissa ${app.name || app.app_id}`);
    pin.title = isPinned(app.app_id) ? "Rimuovi dalle fissate" : "Fissa app";
    const pinIcon = document.createElement("span");
    pinIcon.className = "material-symbols-rounded";
    pinIcon.setAttribute("aria-hidden", "true");
    pinIcon.textContent = isPinned(app.app_id) ? "keep" : "keep_off";
    pin.append(pinIcon);
    pin.addEventListener("click", (event) => {
      event.stopPropagation();
      togglePinnedApp(app).catch((error) => renderEmpty(error.message));
    });

    row.append(button, pin);
    list.append(row);
  });
}

async function togglePinnedApp(app) {
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
  const [registry, pinned] = await Promise.all([
    requestJson("/api/apps"),
    requestJson("/api/apps/app-store/backend", {
      method: "POST",
      body: JSON.stringify({ action: "pinned_apps.list" }),
    }),
  ]);
  state.apps = registry.items || [];
  state.pinnedIds = pinned.pinned_apps || [];
  render();
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
