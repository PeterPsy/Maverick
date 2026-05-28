(function () {
  const APP_ICON_GLYPHS = {
    "agents": "psychology",
    "app-store": "storefront",
    "base-shell": "dashboard",
    "browser": "language",
    "calendar": "calendar_month",
    "checklist": "checklist",
    "chat": "chat",
    "crm": "contacts",
    "developer-kit": "sdk",
    "document-generator": "description",
    "docs-studio": "article",
    "dynamic-views": "dashboard_customize",
    "fleet": "table_chart",
    "gallery": "photo_library",
    "mail": "mail",
    "gmail-app": "mail",
    "maverick-monitor": "monitoring",
    "memory": "neurology",
    "skills": "school",
    "speech": "record_voice_over",
    "storage": "cloud",
    "settings": "admin_panel_settings",
    "vault": "key",
  };

  function includes(list, value) {
    return Array.isArray(list) && list.includes(value);
  }

  function presentation(app = {}, installation = null) {
    if (window.MaverickFrontendPresentation?.frontendPresentation) {
      return window.MaverickFrontendPresentation.frontendPresentation(app, installation);
    }
    const source = installation ? { ...app, ...installation } : app;
    return {
      role: frontendRoleFallback(source),
      launchable: frontendRoleFallback(source) === "workspace" && source.frontend_launchable !== false,
      surfaces: Array.isArray(source.surfaces) ? source.surfaces : [],
    };
  }

  function frontendRoleFallback(app = {}) {
    const role = String(app.frontend_role || app.presentation?.frontend_role || "").trim();
    if (["workspace", "supporting", "none"].includes(role)) {
      return role;
    }
    if (includes(app.surfaces, "supporting_frontend")) {
      return "supporting";
    }
    if (includes(app.surfaces, "frontend")) {
      return "workspace";
    }
    return "none";
  }

  function frontendRole(app = {}, installation = null) {
    return presentation(app, installation).role;
  }

  function frontendLaunchable(app = {}, installation = null) {
    return presentation(app, installation).launchable;
  }

  function glyphName(app = {}, installation = null) {
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
    const surfaces = presentation(app, installation).surfaces;
    if (includes(surfaces, "frontend")) {
      return "web_asset";
    }
    if (includes(surfaces, "supporting_frontend")) {
      return "extension";
    }
    if (includes(surfaces, "mcp")) {
      return "account_tree";
    }
    if (includes(surfaces, "cli")) {
      return "terminal";
    }
    if (includes(surfaces, "backend")) {
      return "dns";
    }
    return "deployed_code";
  }

  function renderIcon(app, className, installation = null) {
    const frame = document.createElement("span");
    frame.className = className;
    frame.setAttribute("aria-hidden", "true");
    if (frontendRole(app, installation) === "supporting") {
      frame.classList.add("is-supporting-frontend");
    }
    if (!frontendLaunchable(app, installation)) {
      frame.classList.add("is-non-launchable");
    }
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
    glyph.textContent = logo?.kind === "glyph" && logo.value ? String(logo.value) : glyphName(app, installation);
    frame.classList.add("is-glyph");
    frame.append(glyph);
    return frame;
  }

  window.MaverickAppIcons = { frontendLaunchable, frontendRole, glyphName, renderIcon };
})();
