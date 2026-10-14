// Shell messages are accepted only from the authenticated parent origin.
export function createPlatformState(platformOrigin, onVisibility) {
  let shellVisible = true;
  const visible = () => shellVisible && document.visibilityState !== "hidden";
  const theme = value => {
    if (value !== "light" && value !== "dark") return;
    document.documentElement.dataset.loopinoTheme = value;
    document.documentElement.style.colorScheme = value;
  };
  window.addEventListener("message", event => {
    if (event.source !== window.parent || event.origin !== platformOrigin) return;
    const message = event.data;
    if (message?.type === "loopino.shell.theme-changed") theme(message.theme?.effective || message.theme?.color_scheme);
    if (message?.type === "loopino.app.visibility-changed" && typeof message.visible === "boolean"
        && (message.app_id || message.owner_app_id) === "browser") {
      shellVisible = message.visible;
      onVisibility();
    }
  });
  document.addEventListener("visibilitychange", onVisibility);
  return {visible};
}
