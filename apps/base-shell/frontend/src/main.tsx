import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { AppShell } from "./AppShell";
import { startTransportRecoveryMonitoring } from "./transportRecovery";
import { registerShellServiceWorker } from "./pwa";
import { applyInitialShellTheme } from "./theme";
import "./styles/main.css";

applyInitialShellTheme();
startTransportRecoveryMonitoring();
registerShellServiceWorker();

createRoot(document.getElementById("root") as HTMLElement).render(
  <StrictMode>
    <AppShell />
  </StrictMode>,
);
