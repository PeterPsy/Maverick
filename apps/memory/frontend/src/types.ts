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
  status?: string;
  revision?: string;
  state_revision?: string;
  state_observation?: string;
  freshness?: string;
  reason?: string;
  verification?: string;
  compilation_state?: string;
  source_state?: string;
};

export type GraphEdge = {
  other_title?: string;
  other_type?: string;
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
  other_title?: string;
  other_type?: string;
  id: string;
  source_node_id: string;
  target_node_id: string;
  kind: string;
  weight?: number;
  confidence?: number;
  reason?: string;
};

export type MemoryCitation = {
  id: string;
  claim_id: string;
  source_id?: string;
  source_version_id?: string;
  source_chunk_id?: string;
  evidence_relation?: string;
  storage_reference?: { deep_link?: string };
  external_ref_id?: string;
  locator?: string;
  quote?: string;
};

export type MemoryClaim = {
  id: string;
  wiki_page_id: string;
  node_id: string;
  claim_text: string;
  status?: string;
  confidence?: number;
  stale?: number;
  citations?: MemoryCitation[];
  contradictions?: MemoryCitation[];
  related_evidence?: MemoryCitation[];
  verification?: string;
  citations_has_more?: boolean;
};

export type CompiledPage = {
  id: string;
  node_id: string;
  title: string;
  summary?: string;
  body_markdown?: string;
  freshness?: string;
  compiled_at?: string;
  verification?: string;
  compilation_state?: string;
  source_state?: string;
};

export type MemorySource = {
  id: string;
  source_kind: string;
  external_ref_id?: string;
  owning_app_id?: string;
  entity_type?: string;
  entity_id?: string;
  file_id?: string;
  workspace_relative_path?: string;
  uri?: string;
  title?: string;
  status?: string;
  external_ref?: ExternalRef;
  storage_reference?: { deep_link?: string };
};

export type LintFinding = {
  id: string;
  finding_type: string;
  severity: string;
  message: string;
  claim_id?: string;
  updated_at?: string;
};

export type NodeDetails = GraphNode & {
  status?: string;
  external_refs?: ExternalRef[];
  outgoing_edges?: DetailedEdge[];
  incoming_edges?: DetailedEdge[];
  compiled_page?: CompiledPage | null;
  claims?: MemoryClaim[];
  citations?: MemoryCitation[];
  sources?: MemorySource[];
  lint_findings?: LintFinding[];
  revisions?: Array<{ id: string; revision: string; reason: string; snapshot?: { title?: string; body_text?: string } }>;
  duplicate_candidates?: Array<{ id: string; title: string; updated_at?: string }>;
  available_source_chunks?: Array<{ chunk_id: string; source_id: string; source_version_id: string; title: string }>;
};

export type ExploreResult = {
  nodes: GraphNode[];
  edges: GraphEdge[];
  snapshot_id: string;
  has_more: boolean;
  next_cursor: string | null;
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
