export type DesignProject = {
  id: string;
  name: string;
  prompt: string;
  status: string;
  source_files: string[];
  imports: Array<{
    workspace_relative_path: string;
    name: string;
    size_bytes: number;
    app_data_path: string;
    imported_at: string;
  }>;
  exports: Array<{
    workspace_relative_paths: string[];
    exported_at: string;
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
  };
};
