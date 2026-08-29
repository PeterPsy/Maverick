import React from "react";
import { createRoot } from "react-dom/client";

import type { AppRegistryItem } from "../../../../base-shell/frontend/src/api";
import { AppFrameHost } from "../../../../base-shell/frontend/src/components/AppFrameHost";
import { parseShellAppRoute } from "../../../../base-shell/frontend/src/navigation";

const route = parseShellAppRoute(window.location.pathname, window.location.search);
if (route.appId !== "design-studio") throw new Error("The shell did not select Design Studio.");

const app: AppRegistryItem = {
  app_id: "design-studio",
  name: "Design Studio",
  version: "e2e",
  description: "Native OpenDesign browser proof",
  publisher: "maverick",
  status: "enabled",
  distribution_mode: "built_in",
  source_access: "platform",
  views: ["workspace"],
  provides: [],
  requires: [],
  logo: null,
  frontend_mount: "/apps/design-studio/",
  frontend_role: "workspace",
  frontend_launchable: true,
  backend_mount: "/api/apps/design-studio/backend",
};

createRoot(document.getElementById("root")!).render(
  <AppFrameHost
    activeApp={app}
    activeAppParams={route.params}
    activeWorkspaceId="e2e-workspace"
    isMobileLayout={false}
    onOpenApp={() => undefined}
  />,
);
