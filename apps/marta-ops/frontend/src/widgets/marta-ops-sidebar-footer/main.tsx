import { createRoot } from "react-dom/client";
import { MartaOpsSidebarFooter } from "./SidebarFooter";
import "../../styles/sidebar-widget.css";

createRoot(document.getElementById("marta-ops-sidebar-footer-root")!).render(
  <MartaOpsSidebarFooter />,
);
