export type OpenDesignNavigation = {
  od_project_id: string;
  od_run_id: string;
};

export type SidecarLaunch = {
  origin: string;
  bootstrap_url: string;
  method: "POST";
  ticket_field: "ticket";
  ticket: string;
  expires_in_seconds: number;
  sidecar_instance_id: string;
};

export type SidecarHostPhase = "launching" | "bootstrapping" | "repairing" | "ready" | "degraded" | "error";

export type SidecarDiagnostic = {
  code: string;
  status: number;
  phase?: string;
  autoRepairable?: boolean;
  retryable?: boolean;
};

export type OpenDesignLaunchTarget = {
  target: "project" | "empty";
  od_project_id: string;
  project: Record<string, unknown> | null;
};

export type OpenDesignNavigateMessage = {
  type: "maverick.opendesign.navigate";
  version: 1;
  od_project_id?: string;
  od_run_id?: string;
};

export type OpenDesignThemeMessage = {
  type: "maverick.opendesign.theme";
  version: 1;
  theme: "dark" | "light";
};

export type OpenDesignOpenSettingsMessage = {
  type: "maverick.opendesign.open-settings";
  version: 1;
  section?: "designSystems";
};

export type OpenDesignOpenToolsMessage = {
  type: "maverick.opendesign.open-tools";
  version: 1;
  request_id: string;
};
