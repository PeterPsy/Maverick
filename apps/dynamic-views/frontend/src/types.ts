export type DynamicViewRenderer = 'sandbox_html_v1';
export type DynamicViewSnapshotMode = 'live' | 'snapshot';

export type DynamicViewSecurityReport = {
  status: 'approved';
  checks: string[];
};

export type DynamicViewPackage = {
  id: string;
  workspace_id: string;
  owner_user_id: string;
  source_instance_id: string | null;
  title: string;
  summary: string;
  renderer: DynamicViewRenderer;
  html: string;
  css: string;
  javascript: string;
  data_schema: Record<string, unknown>;
  security_report: DynamicViewSecurityReport;
  tags: string[];
  status: string;
  asset_manifest_path: string;
  asset_html_path: string;
  created_at: string;
  updated_at: string;
};

export type DynamicViewBinding = {
  source_type: string;
  source_ref: string;
  query?: string | null;
  snapshot?: Record<string, unknown> | null;
};

export type DynamicViewInstance = {
  id: string;
  workspace_id: string;
  owner_user_id: string;
  source_instance_id: string | null;
  package_id: string;
  title: string;
  summary: string;
  package: DynamicViewPackage;
  data: Record<string, unknown>;
  data_bindings: DynamicViewBinding[];
  snapshot_mode: DynamicViewSnapshotMode;
  status: string;
  created_at: string;
  updated_at: string;
};

export type DynamicViewPayload = {
  id: string;
  instanceId?: string;
  title: string;
  summary?: string;
  snapshotMode: DynamicViewSnapshotMode;
  package: {
    id: string;
    title: string;
    summary?: string;
    renderer: DynamicViewRenderer;
    html: string;
    css?: string;
    javascript?: string;
    securityReport?: DynamicViewSecurityReport;
    tags?: string[];
  };
  data: Record<string, unknown>;
  dataBindings: Array<{
    sourceType: string;
    sourceRef: string;
    query?: string | null;
    snapshot?: Record<string, unknown> | null;
  }>;
  createdAt?: string;
  updatedAt?: string;
};

export type DynamicViewCreatePayload = {
  title: string;
  summary?: string;
  package: {
    renderer?: DynamicViewRenderer;
    html: string;
    css?: string;
    javascript?: string;
    dataSchema?: Record<string, unknown>;
    tags?: string[];
  };
  data?: Record<string, unknown>;
  dataBindings?: Array<{
    sourceType: string;
    sourceRef: string;
    query?: string | null;
    snapshot?: Record<string, unknown> | null;
  }>;
  snapshotMode?: DynamicViewSnapshotMode;
};

export type DynamicViewsListPayload = {
  items: DynamicViewInstance[];
};
