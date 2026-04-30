import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { AppShell } from "./AppShell";
import "./styles/main.css";

createRoot(document.getElementById("root") as HTMLElement).render(
  <StrictMode>
    <AppShell />
  </StrictMode>,
);
