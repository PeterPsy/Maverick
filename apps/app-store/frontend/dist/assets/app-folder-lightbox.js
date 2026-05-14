(function () {
  const data = window.MaverickAppFolderData;
  let activeLightbox = null;

  if (!data) {
    window.MaverickAppFolderLightbox = { open: () => null };
    return;
  }

  const { PLACEHOLDER_IMAGE, appImage, createNode, normalizeSurfaces } = data;

  function fallbackIcon() {
    const frame = createNode("span", "folder-lightbox-app-icon app-row-icon is-glyph");
    frame.setAttribute("aria-hidden", "true");
    const glyph = createNode("span", "material-symbols-rounded");
    glyph.textContent = "deployed_code";
    frame.append(glyph);
    return frame;
  }

  function renderLightboxIcon(app, helpers) {
    const icon = helpers.renderIcon ? helpers.renderIcon(app) : fallbackIcon();
    icon.classList.add("folder-lightbox-app-icon");
    return icon;
  }

  function latestVersion(app, helpers) {
    if (helpers.latestVersion) {
      return helpers.latestVersion(app);
    }
    return (app.versions || []).find((version) => version.version === app.latest_version)
      || (app.versions || [])[0]
      || { version: app.latest_version || "" };
  }

  function selectedInstallState(app, helpers) {
    if (helpers.selectedInstallState) {
      return helpers.selectedInstallState(app.app_id);
    }
    return { workspaceCount: 0, installedCount: 0, isInstalledEverywhere: false, isPartiallyInstalled: false };
  }

  function renderMetaPill(text, kind) {
    const pill = createNode("span", "folder-lightbox-pill");
    if (kind) {
      pill.dataset.kind = kind;
    }
    pill.textContent = text;
    return pill;
  }

  function setSlidePosition(lightbox) {
    lightbox.track.style.transform = `translateX(-${lightbox.index * 100}%)`;
  }

  function updateNavState(lightbox) {
    lightbox.prevButton.disabled = lightbox.index <= 0;
    lightbox.nextButton.disabled = lightbox.index >= lightbox.folder.apps.length - 1;
  }

  function renderDots(lightbox) {
    lightbox.dots.replaceChildren();
    lightbox.folder.apps.forEach((_, index) => {
      const dot = createNode("button", "folder-lightbox-dot");
      dot.type = "button";
      dot.setAttribute("aria-label", `Go to app ${index + 1}`);
      dot.dataset.active = index === lightbox.index ? "true" : "false";
      dot.addEventListener("click", (event) => {
        event.stopPropagation();
        navigate(lightbox, index);
      });
      lightbox.dots.append(dot);
    });
  }

  function renderDetails(lightbox) {
    const { helpers } = lightbox.options;
    const app = lightbox.folder.apps[lightbox.index];
    const version = latestVersion(app, helpers) || { version: app.latest_version || "" };
    const installState = selectedInstallState(app, helpers);
    const pending = helpers.isAppPending ? helpers.isAppPending(app.app_id) : false;
    const installed = installState.installedCount > 0;
    const statusText = helpers.statusLabel ? helpers.statusLabel(app.app_id) : installed ? "Installed" : "Not installed";
    const surfaceText = helpers.surfaceLabel ? helpers.surfaceLabel(app) : normalizeSurfaces(app).join(" / ") || "No declared surfaces";

    lightbox.title.textContent = app.name || app.app_id;
    lightbox.description.textContent = app.description || "Ready to install in Maverick.";
    lightbox.counter.textContent = `${lightbox.index + 1} / ${lightbox.folder.apps.length}`;
    lightbox.meta.replaceChildren(
      renderMetaPill(version.version || app.latest_version || "unknown"),
      renderMetaPill(statusText, installed ? "installed" : installState.isPartiallyInstalled ? "partial" : "available"),
      renderMetaPill(surfaceText),
    );
    renderDots(lightbox);

    lightbox.actions.replaceChildren();
    const primary = createNode("button", "folder-lightbox-primary");
    primary.type = "button";
    primary.disabled = pending || (!installed && (!version?.version || installState.workspaceCount === 0));
    const primaryLabel = createNode("span");
    primaryLabel.textContent = installed ? "Open App" : "Get App";
    const primaryIcon = createNode("span", "material-symbols-rounded");
    primaryIcon.setAttribute("aria-hidden", "true");
    primaryIcon.textContent = installed ? "open_in_new" : "download";
    primary.append(primaryLabel, primaryIcon);
    primary.addEventListener("click", (event) => {
      event.stopPropagation();
      if (installed) {
        helpers.openApp?.(app.app_id);
      } else if (version?.version) {
        helpers.installApp?.(app, version);
      }
    });
    lightbox.actions.append(primary);

    if (helpers.renderMoreOptions) {
      const moreOptions = helpers.renderMoreOptions(app, "store", version, installState);
      moreOptions.classList.add("folder-lightbox-options");
      lightbox.actions.append(moreOptions);
    }
  }

  function navigate(lightbox, nextIndex) {
    if (nextIndex < 0 || nextIndex >= lightbox.folder.apps.length || nextIndex === lightbox.index) {
      return;
    }
    lightbox.index = nextIndex;
    lightbox.track.dataset.sliding = "true";
    setSlidePosition(lightbox);
    updateNavState(lightbox);
    renderDetails(lightbox);
    window.setTimeout(() => {
      lightbox.track.dataset.sliding = "false";
    }, 520);
  }

  function close(lightbox) {
    if (!lightbox || lightbox.closing) {
      return;
    }
    lightbox.closing = true;
    lightbox.root.classList.add("is-closing");
    lightbox.stage.style.transform = "translate(0, 0) scale(0.92)";
    window.removeEventListener("keydown", lightbox.handleKeydown);
    document.body.style.overflow = lightbox.previousOverflow || "";
    document.querySelectorAll(".app-folder-preview.is-selected").forEach((node) => node.classList.remove("is-selected"));
    window.setTimeout(() => {
      lightbox.root.remove();
      if (activeLightbox === lightbox) {
        activeLightbox = null;
      }
    }, 520);
  }

  function animateFromSource(lightbox, sourceElement) {
    if (!sourceElement) {
      requestAnimationFrame(() => lightbox.root.classList.add("is-open"));
      return;
    }
    const sourceRect = sourceElement.getBoundingClientRect();
    const targetRect = lightbox.stage.getBoundingClientRect();
    const scale = Math.max(sourceRect.width / targetRect.width, sourceRect.height / targetRect.height);
    const translateX = sourceRect.left + sourceRect.width / 2 - (targetRect.left + targetRect.width / 2);
    const translateY = sourceRect.top + sourceRect.height / 2 - (targetRect.top + targetRect.height / 2);
    lightbox.stage.style.transition = "none";
    lightbox.stage.style.transform = `translate(${translateX}px, ${translateY}px) scale(${scale})`;
    lightbox.stage.style.opacity = "0.5";
    lightbox.stage.style.borderRadius = "12px";
    requestAnimationFrame(() => {
      requestAnimationFrame(() => {
        lightbox.root.classList.add("is-open");
        lightbox.stage.style.transition =
          "transform 700ms cubic-bezier(0.16, 1, 0.3, 1), opacity 600ms ease-out, border-radius 700ms ease";
        lightbox.stage.style.transform = "translate(0, 0) scale(1)";
        lightbox.stage.style.opacity = "1";
        lightbox.stage.style.borderRadius = "24px";
      });
    });
  }

  function renderSlides(folder, helpers) {
    const track = createNode("div", "folder-lightbox-track");
    track.dataset.sliding = "false";
    folder.apps.forEach((app, slideIndex) => {
      const slide = createNode("div", "folder-lightbox-slide");
      const image = createNode("img");
      image.src = appImage(app, folder.id, slideIndex);
      image.alt = "";
      image.loading = "lazy";
      image.addEventListener("error", () => {
        image.src = PLACEHOLDER_IMAGE;
      });
      const shade = createNode("span", "folder-lightbox-slide-shade");
      const icon = renderLightboxIcon(app, helpers);
      slide.append(image, shade, icon);
      track.append(slide);
    });
    return track;
  }

  function open(folder, index, sourceElement, options = {}) {
    if (!folder.apps.length) {
      return null;
    }
    if (activeLightbox) {
      close(activeLightbox);
    }

    const helpers = options.helpers || {};
    const root = createNode("div", "folder-lightbox");
    root.setAttribute("role", "dialog");
    root.setAttribute("aria-modal", "true");

    const backdrop = createNode("div", "folder-lightbox-backdrop");
    const closeButton = renderIconButton("folder-lightbox-close", "Close app carousel", "close");
    const prevButton = renderIconButton("folder-lightbox-nav folder-lightbox-nav--prev", "Previous app", "chevron_left");
    const nextButton = renderIconButton("folder-lightbox-nav folder-lightbox-nav--next", "Next app", "chevron_right");
    const stage = createNode("div", "folder-lightbox-stage");
    const frame = createNode("div", "folder-lightbox-frame");
    const media = createNode("div", "folder-lightbox-media");
    const track = renderSlides(folder, helpers);
    const details = createNode("div", "folder-lightbox-details");
    const copy = createNode("div", "folder-lightbox-copy");
    const title = createNode("h3");
    const description = createNode("p");
    const meta = createNode("div", "folder-lightbox-meta");
    const footer = createNode("div", "folder-lightbox-footer");
    const dots = createNode("div", "folder-lightbox-dots");
    const counter = createNode("p", "folder-lightbox-counter");
    const actions = createNode("div", "folder-lightbox-actions");

    copy.append(title, description, meta);
    footer.append(dots, counter);
    details.append(copy, footer, actions);
    media.append(track);
    frame.append(media, details);
    stage.append(frame);
    root.append(backdrop, closeButton, prevButton, nextButton, stage);
    document.body.append(root);

    const lightbox = {
      actions,
      closing: false,
      counter,
      description,
      dots,
      folder,
      frame,
      index,
      meta,
      nextButton,
      options: { ...options, helpers },
      previousOverflow: document.body.style.overflow,
      prevButton,
      root,
      stage,
      title,
      track,
    };
    lightbox.handleKeydown = (event) => {
      if (event.key === "Escape") {
        close(lightbox);
      } else if (event.key === "ArrowRight") {
        navigate(lightbox, lightbox.index + 1);
      } else if (event.key === "ArrowLeft") {
        navigate(lightbox, lightbox.index - 1);
      }
    };

    activeLightbox = lightbox;
    document.body.style.overflow = "hidden";
    setSlidePosition(lightbox);
    updateNavState(lightbox);
    renderDetails(lightbox);
    animateFromSource(lightbox, sourceElement);

    root.addEventListener("click", () => close(lightbox));
    frame.addEventListener("click", (event) => event.stopPropagation());
    closeButton.addEventListener("click", (event) => {
      event.stopPropagation();
      close(lightbox);
    });
    prevButton.addEventListener("click", (event) => {
      event.stopPropagation();
      navigate(lightbox, lightbox.index - 1);
    });
    nextButton.addEventListener("click", (event) => {
      event.stopPropagation();
      navigate(lightbox, lightbox.index + 1);
    });
    window.addEventListener("keydown", lightbox.handleKeydown);
    closeButton.focus({ preventScroll: true });
    return lightbox;
  }

  function renderIconButton(className, label, iconName) {
    const button = createNode("button", className);
    button.type = "button";
    button.setAttribute("aria-label", label);
    const icon = createNode("span", "material-symbols-rounded");
    icon.setAttribute("aria-hidden", "true");
    icon.textContent = iconName;
    button.append(icon);
    return button;
  }

  window.MaverickAppFolderLightbox = { open };
})();
