import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { MemoryApp } from "./MemoryApp";
import "./styles.css";

createRoot(document.getElementById("root") as HTMLElement).render(
  <StrictMode>
    <MemoryApp />
  </StrictMode>,
);
