export function registerShellServiceWorker(): void {
  if (!import.meta.env.PROD || typeof window === "undefined" || !("serviceWorker" in navigator)) {
    return;
  }

  window.addEventListener("load", () => {
    navigator.serviceWorker.register("/sw.js", { scope: "/" }).catch((error: unknown) => {
      try {
        if (window.localStorage.getItem("maverick3:pwa-debug") === "1") {
          console.warn("Maverick PWA service worker registration failed.", error);
        }
      } catch {
        // Keep PWA diagnostics best-effort; rendering must not depend on browser storage.
      }
    });
  });
}
