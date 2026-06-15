export type DesignProject = {
  id: string;
  name: string;
  prompt: string;
  status: string;
  source_files: string[];
  imports: Array<{
    import_id: string;
    status: string;
    workspace_relative_path: string;
    name: string;
    size_bytes: number;
    app_data_path: string;
    requested_at: string;
    imported_at: string;
    error: string;
  }>;
  exports: Array<{
    export_id: string;
    status: string;
    workspace_relative_paths: string[];
    completed_workspace_relative_paths: string[];
    exported_at: string;
    completed_at: string;
    error: string;
  }>;
  created_at: string;
  updated_at: string;
};

export type DesignStudioState = {
  schema_version: string;
  projects: DesignProject[];
  view_state: {
    query: string;
    selected_project_id: string;
  };
  route_policy: {
    pass_through: string[];
    blocked: string[];
    handled_by_core: string[];
  };
  updated_at: string;
};

export type DesignStudioStatus = {
  state: DesignStudioState;
  sidecar: {
    id: string;
    proxy_url: string;
    ready_url: string;
    version_url: string;
  };
  opendesign: {
    version: string;
    commit: string;
    mode: string;
    bundle: Record<string, string>;
    runtime: {
      bundle_configured: boolean;
      mode: string;
      detail: string;
    };
  };
};
