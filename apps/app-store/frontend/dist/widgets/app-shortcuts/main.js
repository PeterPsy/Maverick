const list = document.querySelector("#appShortcutList");

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
  const icon = document.createElement("span");
  icon.className = "app-shortcuts__icon material-symbols-rounded";
  icon.setAttribute("aria-hidden", "true");
  icon.textContent = iconName(app.app_id);
  return icon;
}

function iconName(appId) {
  const icons = {
    agents: "psychology",
    chat: "add_comment",
    gallery: "photo_library",
    "user-admin": "admin_panel_settings",
  };
  return icons[appId] || "deployed_code";
}

function openApp(appId) {
  const params = appId === "chat" ? { new_chat: true } : undefined;
  window.parent?.postMessage({ type: "maverick.widget.open-app", app_id: appId, params }, window.location.origin);
}

function shortcutLabel(app) {
  if (app.app_id === "chat") {
    return "New Chat";
  }
  return app.name || app.app_id;
}

function renderEmpty(message) {
  list.replaceChildren();
  const empty = document.createElement("p");
  empty.className = "app-shortcuts__empty";
  empty.textContent = message;
  list.append(empty);
}

function render(apps) {
  list.replaceChildren();
  if (!apps.length) {
    renderEmpty("Nessuna app fissata.");
    return;
  }
  apps.forEach((app) => {
    const button = document.createElement("button");
    button.className = "app-shortcuts__button";
    button.type = "button";
    button.addEventListener("click", () => openApp(app.app_id));

    const label = document.createElement("span");
    label.className = "app-shortcuts__label";
    label.textContent = shortcutLabel(app);

    button.append(appIcon(app), label);
    list.append(button);
  });
}

async function load() {
  const [registry, pinned] = await Promise.all([
    requestJson("/api/apps"),
    requestJson("/api/apps/app-store/backend", {
      method: "POST",
      body: JSON.stringify({ action: "pinned_apps.list" }),
    }),
  ]);
  const pinnedIds = pinned.pinned_apps || [];
  const appsById = new Map((registry.items || []).map((app) => [app.app_id, app]));
  render(pinnedIds.map((appId) => appsById.get(appId)).filter(Boolean));
}

window.addEventListener("message", (event) => {
  if (event.origin !== window.location.origin || !event.data || typeof event.data !== "object") {
    return;
  }
  if (event.data.type === "maverick.widget.data-changed" && event.data.owner_app_id === "app-store") {
    load().catch((error) => renderEmpty(error.message));
  }
});

load().catch((error) => renderEmpty(error.message));
