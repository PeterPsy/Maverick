export function applyInitialWidgetTheme() {
  const theme = new URLSearchParams(window.location.search).get("maverick_theme") === "light" ? "light" : "dark";
  document.documentElement.dataset.theme = theme;
  document.documentElement.style.colorScheme = theme;
}

export function listenForWidgetTheme() {
  window.addEventListener("message", (event) => {
    if (event.origin !== window.location.origin || event.source !== window.parent || !event.data || typeof event.data !== "object") {
      return;
    }
    const payload = event.data as { type?: string; theme?: { effective?: string } };
    const theme = payload.theme?.effective;
    if (payload.type === "maverick.shell.theme-changed" && (theme === "dark" || theme === "light")) {
      document.documentElement.dataset.theme = theme;
      document.documentElement.style.colorScheme = theme;
    }
  });
}
