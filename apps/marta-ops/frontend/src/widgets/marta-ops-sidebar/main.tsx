import { createRoot } from "react-dom/client";
import { MartaOpsSidebar } from "./Sidebar";
import "../../styles/sidebar-widget.css";

createRoot(document.getElementById("marta-ops-sidebar-root")!).render(
  <MartaOpsSidebar />,
);
