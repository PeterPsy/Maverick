(function () {
  const FRONTEND_ROLES = new Set(["workspace", "supporting", "none"]);

  function stringList(value) {
    return Array.isArray(value) ? value.filter((item) => typeof item === "string" && item.trim()).map((item) => item.trim()) : [];
  }

  function unique(values) {
    const items = [];
    values.forEach((value) => {
      if (value && !items.includes(value)) {
        items.push(value);
      }
    });
    return items;
  }

  function surfacesFrom(app = {}) {
    const direct = stringList(app.surfaces);
    const provided = Array.isArray(app.provides)
      ? app.provides.flatMap((item) => stringList(item?.surfaces))
      : [];
    return unique([...direct, ...provided]);
  }

  function explicitRole(app = {}) {
    const role = String(app.frontend_role || app.presentation?.frontend_role || "").trim();
    if (FRONTEND_ROLES.has(role)) {
      return role;
    }
    return "";
  }

  function roleFrom(app = {}) {
    const role = explicitRole(app);
    if (role) {
      return role;
    }
    const surfaces = surfacesFrom(app);
    if (surfaces.includes("supporting_frontend")) {
      return "supporting";
    }
    if (surfaces.includes("frontend") || app.frontend_launchable === true) {
      return "workspace";
    }
    return "none";
  }

  function sourceFor(app = {}, installation = null) {
    if (!installation) {
      return app || {};
    }
    return {
      ...app,
      ...installation,
      surfaces: installation.surfaces || app?.surfaces || [],
      provides: installation.provides || app?.provides || [],
      presentation: installation.presentation || { frontend_role: installation.frontend_role || roleFrom(installation) },
    };
  }

  function frontendPresentation(app = {}, installation = null) {
    const source = sourceFor(app, installation);
    const role = roleFrom(source);
    const launchable = role === "workspace" && source.frontend_launchable !== false;
    let surfaces = surfacesFrom(source).filter((surface) => surface !== "frontend" && surface !== "supporting_frontend");
    if (role === "workspace") {
      surfaces = ["frontend", ...surfaces];
    } else if (role === "supporting") {
      surfaces = ["supporting_frontend", ...surfaces];
    }
    return {
      role,
      launchable,
      surfaces: unique(surfaces),
      presentation: { ...(source.presentation || {}), frontend_role: role },
    };
  }

  window.MaverickFrontendPresentation = {
    frontendPresentation,
    frontendRole: (app, installation = null) => frontendPresentation(app, installation).role,
    frontendLaunchable: (app, installation = null) => frontendPresentation(app, installation).launchable,
    normalizeSurfaces: (app, installation = null) => frontendPresentation(app, installation).surfaces,
  };
})();
