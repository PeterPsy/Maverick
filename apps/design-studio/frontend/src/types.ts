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
};

export type SidecarHostPhase = "launching" | "bootstrapping" | "ready" | "degraded" | "error";

export type SidecarDiagnostic = {
  code: string;
  status: number;
};

export type OpenDesignNavigateMessage = {
  type: "maverick.opendesign.navigate";
  version: 1;
  od_project_id?: string;
  od_run_id?: string;
};
