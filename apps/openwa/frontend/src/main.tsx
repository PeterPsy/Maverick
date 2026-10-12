import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { App } from "./App";
import "./native.css";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
