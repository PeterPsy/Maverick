import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { AppShell } from "./AppShell";
import { GoogleBrowserHandoff, isGoogleBrowserHandoff } from "./components/GoogleBrowserHandoff";
import { registerShellServiceWorker } from "./pwa";
import { initializeShellPwaCacheRuntime } from "./pwaCacheRuntime";
import { applyInitialShellTheme } from "./theme";
import "./styles/main.css";
import "./styles/notification-feed.css";

applyInitialShellTheme();
initializeShellPwaCacheRuntime();
registerShellServiceWorker();

createRoot(document.getElementById("root") as HTMLElement).render(
  <StrictMode>
    {isGoogleBrowserHandoff ? <GoogleBrowserHandoff /> : <AppShell />}
  </StrictMode>,
);
