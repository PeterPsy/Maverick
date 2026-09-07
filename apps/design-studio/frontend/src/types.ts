export type SidecarLaunch = {
  origin: string;
  bootstrap_url: string;
  bootstrap_transport: "cors" | "form";
  method: "POST";
  parent_origin: string;
  ticket_field: "ticket";
  ticket: string;
  target_url: string;
  confirmation_token: string;
  expires_in_seconds: number;
  sidecar_instance_id: string;
};

export type SidecarHostPhase = "launching" | "bootstrapping" | "ready" | "error";
