export type SidecarLaunch = {
  origin: string;
  bootstrap_url: string;
  method: "POST";
  ticket_field: "ticket";
  ticket: string;
  confirmation_token: string;
  expires_in_seconds: number;
  sidecar_instance_id: string;
};

export type SidecarHostPhase = "launching" | "bootstrapping" | "ready" | "error";
