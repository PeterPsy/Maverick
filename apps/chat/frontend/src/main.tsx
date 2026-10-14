import React from "react";
import { createRoot } from "react-dom/client";
import { App } from "./App";
import { listenForShellReferenceDrops } from "./lib/shellReferenceDrop";
import { applyInitialLoopinoTheme, listenForLoopinoThemeMessages } from "./lib/shellTheme";
import "./styles/main.css";

applyInitialLoopinoTheme();
listenForLoopinoThemeMessages();
listenForShellReferenceDrops();

createRoot(document.getElementById("root") as HTMLElement).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
);
