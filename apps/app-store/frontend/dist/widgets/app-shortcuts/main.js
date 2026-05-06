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
    renderEmpty("No pinned apps.");
    return;
  }
  apps.forEach((app) => {
    const button = document.createElement("button");
    button.className = "app-shortcuts__button";
    button.type = "button";
    button.addEventListener("click", () => openApp(app.app_id));

    const label = document.createElement("span");
    label.className = "app-shortcuts__label";
    label.textContent = app.name || app.app_id;

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
