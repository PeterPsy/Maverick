(function () {
  const APP_ICON_GLYPHS = {
    "agents": "psychology",
    "app-store": "storefront",
    "base-shell": "dashboard",
    "checklist": "checklist",
    "chat": "chat",
    "crm": "contacts",
    "developer-kit": "sdk",
    "document-generator": "description",
    "docs-studio": "article",
    "dynamic-views": "dashboard_customize",
    "fleet": "table_chart",
    "gallery": "photo_library",
    "gmail-app": "mail",
    "maverick-monitor": "monitoring",
    "memory": "neurology",
    "skills": "school",
    "storage": "cloud",
    "user-admin": "admin_panel_settings",
  };

  function includes(list, value) {
    return Array.isArray(list) && list.includes(value);
  }

  function glyphName(app = {}) {
    const appId = String(app.app_id || app.public_app_id || "").trim();
    if (APP_ICON_GLYPHS[appId]) {
      return APP_ICON_GLYPHS[appId];
    }
    if (includes(app.views, "chat")) {
      return "forum";
    }
    if (includes(app.views, "agents")) {
      return "smart_toy";
    }
    if (includes(app.views, "shell")) {
      return "dashboard";
    }
    if (includes(app.surfaces, "frontend")) {
      return "web_asset";
    }
    if (includes(app.surfaces, "mcp")) {
      return "account_tree";
    }
    if (includes(app.surfaces, "cli")) {
      return "terminal";
    }
    if (includes(app.surfaces, "backend")) {
      return "dns";
    }
    return "deployed_code";
  }

  function renderIcon(app, className) {
    const frame = document.createElement("span");
    frame.className = className;
    frame.setAttribute("aria-hidden", "true");
    const logo = app?.logo;
    if (logo?.kind === "image" && logo.value) {
      const image = document.createElement("img");
      image.alt = "";
      image.loading = "lazy";
      image.src = String(logo.value);
      frame.classList.add("is-image");
      frame.append(image);
      return frame;
    }
    const glyph = document.createElement("span");
    glyph.className = "material-symbols-rounded";
    glyph.textContent = logo?.kind === "glyph" && logo.value ? String(logo.value) : glyphName(app);
    frame.classList.add("is-glyph");
    frame.append(glyph);
    return frame;
  }

  window.MaverickAppIcons = { glyphName, renderIcon };
})();
