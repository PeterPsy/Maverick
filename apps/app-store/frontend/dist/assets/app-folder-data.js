(function () {
  const PLACEHOLDER_IMAGE =
    "https://images.unsplash.com/photo-1618005182384-a83a8bd57fbe?auto=format&fit=crop&q=80&w=1200";

  const FOLDER_TYPES = [
    {
      id: "frontend",
      title: "Frontend Apps",
      singular: "frontend app",
      gradient: "linear-gradient(135deg, #00c6ff, #0072ff)",
      accent: "#00c6ff",
      surfaces: ["frontend"],
    },
    {
      id: "backend",
      title: "Backend Services",
      singular: "backend service",
      gradient: "linear-gradient(135deg, #2dd4bf, #0f766e)",
      accent: "#2dd4bf",
      surfaces: ["backend"],
    },
    {
      id: "mcp",
      title: "MCP Tools",
      singular: "MCP tool",
      gradient: "linear-gradient(135deg, #f59e0b, #ef4444)",
      accent: "#f59e0b",
      surfaces: ["mcp"],
    },
    {
      id: "cli",
      title: "CLI Utilities",
      singular: "CLI utility",
      gradient: "linear-gradient(135deg, #a3e635, #16a34a)",
      accent: "#a3e635",
      surfaces: ["cli"],
    },
    {
      id: "skills",
      title: "Skills & Widgets",
      singular: "extension",
      gradient: "linear-gradient(135deg, #f80759, #bc4e9c)",
      accent: "#f80759",
      surfaces: ["skills", "widgets"],
    },
    {
      id: "other",
      title: "Maverick Apps",
      singular: "app",
      gradient: "linear-gradient(135deg, #8e2de2, #4a00e0)",
      accent: "#8e2de2",
      surfaces: [],
    },
  ];

  const IMAGE_POOLS = {
    frontend: [
      "https://images.unsplash.com/photo-1547658719-da2b51169166?auto=format&fit=crop&q=80&w=900",
      "https://images.unsplash.com/photo-1498050108023-c5249f4df085?auto=format&fit=crop&q=80&w=900",
      "https://images.unsplash.com/photo-1559028012-481c04fa702d?auto=format&fit=crop&q=80&w=900",
    ],
    backend: [
      "https://images.unsplash.com/photo-1558494949-ef010cbdcc31?auto=format&fit=crop&q=80&w=900",
      "https://images.unsplash.com/photo-1518432031352-d6fc5c10da5a?auto=format&fit=crop&q=80&w=900",
      "https://images.unsplash.com/photo-1531297484001-80022131f5a1?auto=format&fit=crop&q=80&w=900",
    ],
    mcp: [
      "https://images.unsplash.com/photo-1515879218367-8466d910aaa4?auto=format&fit=crop&q=80&w=900",
      "https://images.unsplash.com/photo-1550751827-4bd374c3f58b?auto=format&fit=crop&q=80&w=900",
      "https://images.unsplash.com/photo-1550745165-9bc0b252726f?auto=format&fit=crop&q=80&w=900",
    ],
    cli: [
      "https://images.unsplash.com/photo-1517694712202-14dd9538aa97?auto=format&fit=crop&q=80&w=900",
      "https://images.unsplash.com/photo-1461749280684-dccba630e2f6?auto=format&fit=crop&q=80&w=900",
      "https://images.unsplash.com/photo-1504639725590-34d0984388bd?auto=format&fit=crop&q=80&w=900",
    ],
    skills: [
      "https://images.unsplash.com/photo-1552664730-d307ca884978?auto=format&fit=crop&q=80&w=900",
      "https://images.unsplash.com/photo-1558655146-d09347e92766?auto=format&fit=crop&q=80&w=900",
      "https://images.unsplash.com/photo-1551650975-87deedd944c3?auto=format&fit=crop&q=80&w=900",
    ],
    other: [
      "https://images.unsplash.com/photo-1618005182384-a83a8bd57fbe?auto=format&fit=crop&q=80&w=900",
      "https://images.unsplash.com/photo-1634017839464-5c339ebe3cb4?auto=format&fit=crop&q=80&w=900",
      "https://images.unsplash.com/photo-1614850523296-d8c1af93d400?auto=format&fit=crop&q=80&w=900",
    ],
  };

  function createNode(tagName, className) {
    const node = document.createElement(tagName);
    if (className) {
      node.className = className;
    }
    return node;
  }

  function normalizeSurfaces(app) {
    return Array.isArray(app?.surfaces) ? app.surfaces.filter(Boolean) : [];
  }

  function hashString(value) {
    return String(value || "").split("").reduce((hash, char) => ((hash << 5) - hash + char.charCodeAt(0)) | 0, 0);
  }

  function folderDefinition(folderId) {
    return FOLDER_TYPES.find((folder) => folder.id === folderId) || FOLDER_TYPES[FOLDER_TYPES.length - 1];
  }

  function folderIdForApp(app, activeSurface) {
    const surfaces = normalizeSurfaces(app);
    if (activeSurface && surfaces.includes(activeSurface)) {
      return activeSurface === "widgets" ? "skills" : activeSurface;
    }
    const match = FOLDER_TYPES.find((folder) => folder.surfaces.some((surface) => surfaces.includes(surface)));
    return match?.id || "other";
  }

  function buildFolders(apps, activeSurface) {
    const folders = new Map();
    apps.forEach((app) => {
      const folderId = folderIdForApp(app, activeSurface);
      if (!folders.has(folderId)) {
        folders.set(folderId, { ...folderDefinition(folderId), apps: [] });
      }
      folders.get(folderId).apps.push(app);
    });
    return FOLDER_TYPES.map((definition) => folders.get(definition.id)).filter(Boolean);
  }

  function appImage(app, folderId, index) {
    const logo = app?.logo;
    if (logo?.kind === "image" && logo.value) {
      return String(logo.value);
    }
    const pool = IMAGE_POOLS[folderId] || IMAGE_POOLS.other;
    const offset = Math.abs(hashString(app?.app_id || app?.name || index));
    return pool[offset % pool.length] || PLACEHOLDER_IMAGE;
  }

  function renderCount(folder) {
    const count = folder.apps.length;
    return `${count} ${count === 1 ? folder.singular : "apps"}`;
  }

  window.MaverickAppFolderData = {
    PLACEHOLDER_IMAGE,
    appImage,
    buildFolders,
    createNode,
    normalizeSurfaces,
    renderCount,
  };
})();
