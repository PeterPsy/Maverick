(function () {
  const FOLDER_TYPES = [
    {
      id: "frontend",
      title: "Frontend Apps",
      gradient: "linear-gradient(135deg, #00c6ff, #0072ff)",
      accent: "#00c6ff",
      surfaces: ["frontend"],
    },
    {
      id: "backend",
      title: "Backend Services",
      gradient: "linear-gradient(135deg, #d4d4d4, #737373)",
      accent: "#d4d4d4",
      surfaces: ["backend"],
    },
    {
      id: "supporting_frontend",
      title: "Platform Extensions",
      gradient: "linear-gradient(135deg, #111111, #f5f5f5)",
      accent: "#f5f5f5",
      surfaces: ["supporting_frontend"],
    },
    {
      id: "mcp",
      title: "MCP Tools",
      gradient: "linear-gradient(135deg, #f59e0b, #ef4444)",
      accent: "#f59e0b",
      surfaces: ["mcp"],
    },
    {
      id: "cli",
      title: "CLI Utilities",
      gradient: "linear-gradient(135deg, #e5e5e5, #525252)",
      accent: "#e5e5e5",
      surfaces: ["cli"],
    },
    {
      id: "skills",
      title: "Skills & Widgets",
      gradient: "linear-gradient(135deg, #f80759, #bc4e9c)",
      accent: "#f80759",
      surfaces: ["skills", "widgets"],
    },
    {
      id: "other",
      title: "Maverick Apps",
      gradient: "linear-gradient(135deg, #8e2de2, #4a00e0)",
      accent: "#8e2de2",
      surfaces: [],
    },
  ];

  function createNode(tagName, className) {
    const node = document.createElement(tagName);
    if (className) {
      node.className = className;
    }
    return node;
  }

  function normalizeSurfaces(app) {
    if (window.MaverickFrontendPresentation?.normalizeSurfaces) {
      return window.MaverickFrontendPresentation.normalizeSurfaces(app);
    }
    return Array.isArray(app?.surfaces) ? app.surfaces.filter(Boolean) : [];
  }

  function folderIdsForApp(app, activeSurface) {
    const surfaces = normalizeSurfaces(app);
    if (activeSurface && surfaces.includes(activeSurface)) {
      return [activeSurface === "widgets" ? "skills" : activeSurface];
    }
    if (activeSurface) {
      return [];
    }
    const matchedFolderIds = FOLDER_TYPES
      .filter((folder) => folder.surfaces.some((surface) => surfaces.includes(surface)))
      .map((folder) => folder.id);
    return matchedFolderIds.length ? [...new Set(matchedFolderIds)] : ["other"];
  }

  function folderAppKey(app) {
    return [app?.storeMode || "", app?.workspace_id || "", app?.app_id || app?.name || ""].join(":");
  }

  function addAppToFolder(folder, app) {
    const key = folderAppKey(app);
    if (folder.apps.some((existing) => folderAppKey(existing) === key)) {
      return;
    }
    folder.apps.push(app);
  }

  function buildFolders(apps, activeSurface) {
    const folders = new Map(FOLDER_TYPES.map((definition) => [definition.id, { ...definition, apps: [] }]));
    apps.forEach((app) => {
      folderIdsForApp(app, activeSurface).forEach((folderId) => {
        const folder = folders.get(folderId) || folders.get("other");
        addAppToFolder(folder, app);
      });
    });
    return FOLDER_TYPES.map((definition) => folders.get(definition.id));
  }

  window.MaverickAppFolderData = {
    buildFolders,
    createNode,
    normalizeSurfaces,
  };
})();
