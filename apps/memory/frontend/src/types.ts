export type NodeType =
  | "note"
  | "fact"
  | "decision"
  | "file_ref"
  | "app_entity_ref"
  | "person_ref"
  | "company_ref"
  | "project_ref"
  | "topic"
  | "question";

export type GraphNode = {
  id: string;
  type: NodeType | string;
  title: string;
  summary?: string;
  body_text?: string;
  importance?: number;
  confidence?: number;
  created_at?: string;
  updated_at?: string;
  metadata?: Record<string, unknown>;
  x?: number;
  y?: number;
  vx?: number;
  vy?: number;
  radius?: number;
};

export type GraphEdge = {
  id?: string;
  source: string;
  target: string;
  kind: string;
  weight?: number;
  confidence?: number;
  reason?: string;
};

export type ExternalRef = {
  id: string;
  ref_kind: string;
  owning_app_id?: string;
  entity_type?: string;
  entity_id?: string;
  file_id?: string;
  workspace_relative_path?: string;
  uri?: string;
  title?: string;
};

export type DetailedEdge = {
  id: string;
  source_node_id: string;
  target_node_id: string;
  kind: string;
  weight?: number;
  confidence?: number;
  reason?: string;
};

export type NodeDetails = GraphNode & {
  status?: string;
  external_refs?: ExternalRef[];
  outgoing_edges?: DetailedEdge[];
  incoming_edges?: DetailedEdge[];
};

export type NodeDraft = {
  title: string;
  body: string;
  type: string;
};

export type ViewFilter = {
  mode: "search" | "custom";
  title: string;
  query: string;
  refs: Array<{ entity_type: string; entity_id: string }>;
  updated_at?: string;
};

export type RelationshipRow = GraphEdge & {
  otherId: string;
  other?: GraphNode;
  direction: string;
};
