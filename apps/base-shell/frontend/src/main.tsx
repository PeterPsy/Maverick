import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { AppShell } from "./AppShell";
import { registerShellServiceWorker } from "./pwa";
import "./styles/main.css";

registerShellServiceWorker();

createRoot(document.getElementById("root") as HTMLElement).render(
  <StrictMode>
    <AppShell />
  </StrictMode>,
);
