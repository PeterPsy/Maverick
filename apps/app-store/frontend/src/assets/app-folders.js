(function () {
  const data = window.MaverickAppFolderData;
  const lightbox = window.MaverickAppFolderLightbox;

  if (!data || !lightbox) {
    window.MaverickAppFolderView = { render: () => null };
    return;
  }

  const { buildFolders, createNode } = data;
  const TWO_STEP_FOLDER_QUERY = "(max-width: 720px), ((hover: none) and (pointer: coarse))";

  function fallbackPreviewIcon() {
    const frame = createNode("span", "app-folder-preview-icon app-row-icon is-glyph");
    frame.setAttribute("aria-hidden", "true");
    const glyph = createNode("span", "material-symbols-rounded");
    glyph.textContent = "deployed_code";
    frame.append(glyph);
    return frame;
  }

  function renderPreviewIcon(app, helpers) {
    const installState = helpers.selectedInstallState ? helpers.selectedInstallState(app.app_id) : null;
    const icon = helpers.renderIcon ? helpers.renderIcon(app, installState?.presentationInstallation || null) : fallbackPreviewIcon();
    icon.classList.add("app-folder-preview-icon");
    return icon;
  }

  function makePreviewButton(folder, app, index, totalCount, options) {
    const button = createNode("button", "app-folder-preview");
    button.type = "button";
    button.setAttribute("aria-label", `Open ${app.name || app.app_id} in ${folder.title}`);

    const middleIndex = (totalCount - 1) / 2;
    const factor = totalCount > 1 ? (index - middleIndex) / middleIndex : 0;
    button.style.setProperty("--folder-card-rotation", `${factor * 25}deg`);
    button.style.setProperty("--folder-card-x", `${factor * 85}px`);
    button.style.setProperty("--folder-card-y", `${Math.abs(factor) * 12}px`);
    button.style.setProperty("--folder-card-delay", `${index * 50}ms`);
    button.style.zIndex = String(10 + index);

    const helpers = options.helpers || {};
    const frame = createNode("span", "app-folder-preview-frame");
    const icon = renderPreviewIcon(app, helpers);
    const title = createNode("span", "app-folder-preview-title");
    title.textContent = app.name || app.app_id;
    frame.append(icon, title);
    button.append(frame);

    button.addEventListener("click", (event) => {
      event.preventDefault();
      event.stopPropagation();
      button.classList.add("is-selected");
      lightbox.open(folder, index, button, options);
    });

    return button;
  }

  function renderFolder(folder, folderIndex, options) {
    const card = createNode("article", "app-folder-card");
    card.style.setProperty("--folder-gradient", folder.gradient);
    card.style.setProperty("--folder-accent", folder.accent);
    card.style.animationDelay = `${120 + folderIndex * 80}ms`;
    card.setAttribute("aria-label", folder.title);
    if (folder.apps.length) {
      card.tabIndex = 0;
    } else {
      card.classList.add("is-empty");
      card.setAttribute("aria-disabled", "true");
    }

    const glow = createNode("div", "app-folder-glow");
    const scene = createNode("div", "app-folder-scene");
    const back = createNode("div", "app-folder-back");
    const tab = createNode("div", "app-folder-tab");
    const previewLayer = createNode("div", "app-folder-preview-layer");
    const front = createNode("div", "app-folder-front");
    const shine = createNode("div", "app-folder-shine");
    const previewApps = folder.apps.slice(0, 5);

    previewApps.forEach((app, index) => {
      previewLayer.append(makePreviewButton(folder, app, index, previewApps.length, options));
    });

    scene.append(back, tab, previewLayer, front, shine);
    card.append(glow, scene, renderFolderCopy(folder), renderHint(folder));
    if (folder.apps.length) {
      bindFolderEvents(card, folder, options);
    }
    return card;
  }

  function renderFolderCopy(folder) {
    const copy = createNode("div", "app-folder-copy");
    const title = createNode("h3");
    title.textContent = folder.title;
    copy.append(title);
    return copy;
  }

  function folderAppCount(folder) {
    const count = folder.apps.length;
    return `${count} ${count === 1 ? "app" : "apps"}`;
  }

  function renderHint(folder) {
    const hint = createNode("div", "app-folder-hint");
    hint.textContent = folderAppCount(folder);
    return hint;
  }

  function shouldUseTwoStepFolderOpen() {
    return typeof window.matchMedia === "function" && window.matchMedia(TWO_STEP_FOLDER_QUERY).matches;
  }

  function primeFolderFan(card) {
    document.querySelectorAll(".app-folder-card.is-hovered").forEach((node) => {
      if (node !== card) {
        node.classList.remove("is-hovered");
        node.classList.remove("is-touch-primed");
      }
    });
    card.classList.add("is-hovered");
    card.classList.add("is-touch-primed");
  }

  function bindFolderEvents(card, folder, options) {
    card.addEventListener("mouseenter", () => card.classList.add("is-hovered"));
    card.addEventListener("mouseleave", () => card.classList.remove("is-hovered"));
    card.addEventListener("focusin", () => card.classList.add("is-hovered"));
    card.addEventListener("focusout", (event) => {
      if (!card.contains(event.relatedTarget)) {
        card.classList.remove("is-hovered");
      }
    });
    card.addEventListener("click", (event) => {
      if (shouldUseTwoStepFolderOpen() && !card.classList.contains("is-touch-primed")) {
        event.preventDefault();
        primeFolderFan(card);
        return;
      }
      lightbox.open(folder, 0, card, options);
    });
    card.addEventListener("keydown", (event) => {
      if (event.key === "Enter" || event.key === " ") {
        event.preventDefault();
        lightbox.open(folder, 0, card, options);
      }
    });
  }

  function render({ mount, apps, activeSurface = "", helpers = {} }) {
    if (!mount) {
      return;
    }
    const folders = buildFolders(apps || [], activeSurface);
    if (!folders.length) {
      const empty = createNode("p", "empty-state");
      empty.textContent = "No apps match the current filters.";
      mount.replaceChildren(empty);
      return;
    }
    const grid = createNode("div", "app-folder-grid");
    folders.forEach((folder, index) => {
      grid.append(renderFolder(folder, index, { helpers }));
    });
    mount.replaceChildren(grid);
  }

  window.MaverickAppFolderView = { render };
})();
