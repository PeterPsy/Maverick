import React from "react";
import { createRoot } from "react-dom/client";
import { App } from "./App";
import { applyInitialMaverickTheme, listenForMaverickThemeMessages } from "./lib/shellTheme";
import "./styles/main.css";

applyInitialMaverickTheme();
listenForMaverickThemeMessages();

createRoot(document.getElementById("root") as HTMLElement).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
);
