export type ProviderItem = {
  provider_id: string;
  label: string;
  description: string;
  kind?: string;
  provider_role?: string;
  status: string;
  default_model_family: string | null;
  model_options?: ProviderModelOption[];
  capabilities?: Record<string, boolean>;
  hosted_provider_id?: string;
  hosted_model_id?: string;
  input_modalities?: string[];
  output_modalities?: string[];
};

export type ProviderReasoningOption = {
  effort: string;
  label: string;
  description: string | null;
};

export type ProviderModelOption = {
  model_id: string;
  label: string;
  description: string | null;
  default_reasoning_effort: string | null;
  supported_reasoning_efforts: ProviderReasoningOption[];
  input_modalities?: string[];
  output_modalities?: string[];
  upstream_provider_options?: Array<Record<string, unknown>>;
};

export type ProviderModelSettings = {
  selected_model_id: string | null;
  selected_reasoning_effort: string | null;
  available_models: ProviderModelOption[];
};

export type HostedProviderSelection = {
  workspace_id: string;
  profile: string;
  provider_id: string;
  selection_reason: string;
  updated_at: string;
  model_id: string | null;
};

export type HostedTextProviderStatus = {
  profile: string;
  active_provider: ProviderItem | null;
  selection: HostedProviderSelection | null;
  model_settings: ProviderModelSettings | null;
  available_providers: ProviderItem[];
  route_preview?: {
    selected_provider_id: string | null;
    selected_model_id_or_voice_id: string | null;
    selected_runtime_engine_id: string | null;
    execution_path: string | null;
    reason_codes: string[];
  } | null;
};

export type ProviderPayload = {
  workspace_id: string;
  configured?: boolean;
  active_provider: ProviderItem | null;
  hosted_text?: HostedTextProviderStatus | null;
  blocked_reason?: string | null;
  blocked_detail?: string | null;
  items?: ProviderItem[];
  available_providers?: ProviderItem[];
};

export type DependencyProviderCandidate = {
  app_id: string;
  name: string;
  version: string;
  interface: string;
  interface_version: string;
  description: string;
  surfaces: string[];
};

export type DependencyResolutionItem = {
  alias: string;
  interface: string;
  version: string;
  required: boolean;
  cardinality: string;
  description: string;
  status: string;
  candidates: DependencyProviderCandidate[];
  selected_provider_app_ids: string[];
  stale_provider_app_ids: string[];
  blocked_reason: string | null;
};

export type AppDependenciesPayload = {
  workspace_id: string;
  consumer_app_id: string;
  status: string;
  dependencies: DependencyResolutionItem[];
};

export type AgentTypeSummary = {
  id: string;
  name: string;
  description: string;
  role_id: string;
  skill_ids: string[];
  trace_verbosity: string;
  enabled: boolean;
};

export type AgentCatalogPayload = {
  workspace_id?: string;
  agent_types?: AgentTypeSummary[];
};

export type AgentDefinition = AgentTypeSummary & {
  role_name?: string;
  role_description?: string;
  instructions?: string;
};

export type AgentDefinitionPayload = {
  exists: boolean;
  agent_definition?: AgentDefinition;
};

export type AgentPromptPreviewPayload = {
  rendered: string;
};

export type SpeechCapabilitiesPayload = {
  app_id?: string;
  interfaces?: {
    "speech.synthesis"?: {
      available?: boolean;
      provider_available?: boolean;
      content_types?: string[];
      max_text_chars?: number;
      quality_profile?: string;
      latency_profile?: string;
    };
    "speech.transcription"?: {
      available?: boolean;
      provider_available?: boolean;
      content_types?: string[];
      max_audio_bytes?: number;
      max_inline_audio_bytes?: number;
      max_file_audio_bytes?: number;
      max_duration_seconds?: number;
      max_inline_duration_seconds?: number;
      streaming_supported?: boolean;
      chunked_dictation_supported?: boolean;
      language_detection?: string;
      language_hint_supported?: boolean;
      profiles?: string[];
      inline_default_profile?: string;
      inline_default_profile_available?: boolean;
      inline_default_profile_engine?: string;
    };
  };
};

export type SpeechSynthesizePayload = {
  job_id?: string;
  content_type?: string;
  audio_base64?: string;
  audio_data_url?: string;
  retention?: string;
  size_bytes?: number;
};

export type SpeechTranscribePayload = {
  job_id?: string;
  text: string;
  segments?: Array<{ start?: number; end?: number; text?: string }>;
  language?: string;
  language_probability?: number;
  duration_seconds?: number;
  engine?: string;
  model?: string;
  profile?: string;
  beam_size?: number;
  worker?: Record<string, unknown>;
  metrics?: Record<string, unknown>;
  commands?: Array<{ type?: string; text?: string }>;
  session_id?: string;
  chunk_index?: number;
  chunk_text?: string;
  partial?: boolean;
  final?: boolean;
  retention?: string;
  size_bytes?: number;
};

export type SpeechTranscribeOptions = {
  language?: string;
  profile?: string;
  sessionId?: string;
  chunkIndex?: number;
  final?: boolean;
  dictation?: boolean;
};

export type ChatThread = {
  thread_id: string;
  runtime_session_id: string;
  title: string;
  title_pending?: boolean;
  title_source?: string;
  title_generation_failure?: string | null;
  agent_label: string;
  agent_type_id: string;
  agent_role_id: string;
  source_app_id: string;
  system_prompt: string;
  project_id: string | null;
  archived: boolean;
  availability: string;
  created_at: string;
  updated_at: string;
  last_user_message_at?: string | null;
  last_completed_response_at?: string | null;
  last_completed_turn_id?: string | null;
  has_unread_completed_response?: boolean;
};

export type ChatProject = {
  project_id: string;
  name: string;
  created_at: string;
  updated_at: string;
};

export type ChatSidebarPayload = {
  threads: ChatThread[];
  projects?: ChatProject[];
  preferences?: Record<string, unknown>;
};

export type ChatProjectsPayload = {
  projects: ChatProject[];
  preferences?: Record<string, unknown>;
};

export type RuntimeCleanup = {
  session_id: string;
  found: boolean;
  terminated_processes: number;
  cancelled_turns: number;
  deleted_threads?: number;
  runtime_root_deleted?: boolean;
};

export type DeleteThreadPayload = ChatSidebarPayload & {
  deleted_thread_id?: string;
  deleted_runtime_session_id?: string;
  runtime_cleanup?: RuntimeCleanup;
};

export type RuntimeSession = {
  session_id: string;
  workspace_id: string;
  agent_id: string;
  status: string;
  effective_mode: string;
  runtime_mode?: "agentic" | "plain_hosted_chat" | string;
  skill_catalog_app_id?: string | null;
  provider_id?: string;
};

export type RuntimeTurn = {
  turn_id: string;
  session_id: string;
  workspace_id: string;
  status: string;
  input_text: string | null;
  failure_reason: string | null;
  runtime_mode?: "agentic" | "plain_hosted_chat" | string;
  created_at: string;
  updated_at: string;
};

export type RuntimeEvent = {
  event_id: string;
  session_id: string;
  turn_id: string | null;
  event_type: string;
  payload: Record<string, unknown>;
  created_at: string;
};

export type RuntimeWebSocketFrame =
  | {
      type: "runtime.snapshot";
      session: RuntimeSession;
      events: RuntimeEvent[];
      turns?: RuntimeTurn[];
      last_event_id: string | null;
      has_more_before?: boolean;
      oldest_event_id?: string | null;
    }
  | {
      type: "runtime.history.page";
      events: RuntimeEvent[];
      turns?: RuntimeTurn[];
      before_event_id: string | null;
      oldest_event_id: string | null;
      newest_event_id: string | null;
      has_more_before: boolean;
    }
  | { type: "runtime.event"; event: RuntimeEvent }
  | { type: "runtime.heartbeat"; session_id: string; at: string };

export type RuntimeThreadWebSocketFrame =
  | { type: "runtime.thread.snapshot"; workspace_id: string; threads: ChatThread[]; at: string }
  | {
      type: "runtime.thread.changed";
      workspace_id: string;
      action: string;
      threads: ChatThread[];
      thread?: ChatThread;
      deleted_thread_ids?: string[];
      deleted_runtime_session_ids?: string[];
    }
  | { type: "runtime.thread.heartbeat"; workspace_id: string; at: string };

export type ChatMessage = {
  id: string;
  role: "human" | "agent" | "system" | "tool" | "structured" | "step";
  content: string;
  createdAt: string;
  status?: "pending" | "failed" | "complete";
  attachments?: ChatMessageAttachment[];
  appReferences?: AppReference[];
  structuredContent?: StructuredContent;
  toolCall?: ToolCallMessage;
  toolCalls?: ToolCallMessage[];
  step?: RuntimeStepMessage;
};

export type AppAppReference = {
  type: "app";
  app_id: string;
  label?: string;
};

export type AppEntityReference = {
  type: "entity";
  app_id: string;
  entity_type: string;
  entity_id: string;
  label: string;
  summary?: string;
  deep_link?: string;
  exists?: boolean;
};

export type AppReference = AppAppReference | AppEntityReference;

export type SearchAppReferencesOptions = {
  appIds?: string[];
  entityTypes?: string[];
  limit?: number;
};

export type ChatMessageAttachment = {
  id: string;
  name: string;
  size: number;
  type: string;
  isImage: boolean;
  objectUrl?: string | null;
  warning?: string | null;
  fileId?: string;
  relativePath?: string;
};

export type UploadedWorkspaceFile = {
  file_id: string;
  workspace_id: string;
  relative_path: string;
  filename: string;
  content_type: string;
  size_bytes: number;
  sha256: string;
  created_at: string;
};

export type StructuredContent = {
  kind: string;
  payload: Record<string, unknown>;
};

export type ToolCallMessage = {
  id?: string;
  name: string;
  status: "started" | "updated" | "completed" | "failed";
  detail: Record<string, unknown>;
  createdAt?: string;
};

export type RuntimeStepMessage = {
  label: string;
  detail: Record<string, unknown>;
};

export type MultiAgentComposerMode = "off" | "auto" | "multi" | "group_chat";
export type InterAgentVisibilityPlane = "summary" | "detail" | "debug";

export type InterAgentRunStatus =
  | "created"
  | "planning"
  | "running"
  | "paused"
  | "waiting_approval"
  | "completed"
  | "failed"
  | "cancelled"
  | "recovering";

export type InterAgentRunRecord = {
  run_id: string;
  workspace_id: string;
  thread_id: string;
  root_runtime_session_id: string;
  source_app_id: string;
  mode: string;
  status: InterAgentRunStatus;
  created_by_user_id: string;
  orchestrator_participant_id: string;
  budget_policy_id: string;
  budget_ledger_id: string;
  visibility_level: InterAgentVisibilityPlane;
  created_at: string;
  updated_at: string;
  ended_at?: string | null;
};

export type InterAgentParticipantRecord = {
  participant_id: string;
  workspace_id: string;
  run_id: string;
  kind: string;
  execution_mode: string;
  agent_type_id?: string | null;
  label: string;
  runtime_session_id?: string | null;
  status: string;
  current_task_id?: string | null;
  thread_visibility: string;
  created_at: string;
  updated_at: string;
  sequence_index: number;
};

export type InterAgentEdgeRecord = {
  edge_id: string;
  workspace_id: string;
  run_id: string;
  source_id: string;
  target_id: string;
  kind: string;
  label: string;
  status: string;
  created_at: string;
};

export type InterAgentBudgetPolicyRecord = {
  budget_policy_id: string;
  workspace_id: string;
  max_participants: number;
  max_concurrent_participants: number;
  max_handoffs: number;
  max_rounds: number;
  max_total_turns: number;
  max_turns_per_participant: number;
  max_tool_calls: number;
  max_estimated_tokens: number;
  max_estimated_cost: string;
  max_idle_seconds: number;
  max_stall_seconds: number;
  approval_required_above_cost: string;
  created_at: string;
};

export type InterAgentBudgetLedgerRecord = {
  budget_ledger_id: string;
  workspace_id: string;
  run_id: string;
  reserved_participants: number;
  running_participants: number;
  turns_used: number;
  tool_calls_used: number;
  handoffs_used: number;
  estimated_tokens_used: number;
  estimated_cost_used: string;
  updated_at: string;
};

export type InterAgentApprovalRecord = {
  approval_id: string;
  workspace_id: string;
  run_id: string;
  participant_id: string;
  requested_by_participant_id: string;
  operation_kind: string;
  resource_refs: Array<Record<string, unknown>>;
  summary: string;
  risk_level: string;
  status: "pending" | "approved" | "rejected" | "expired" | "cancelled";
  eligible_approver_user_ids: string[];
  eligible_approver_roles: string[];
  expires_at: string;
  resolved_by_user_id?: string | null;
  resolved_at?: string | null;
  resolution_reason?: string | null;
};

export type InterAgentEventRecord = {
  event_id: string;
  workspace_id: string;
  run_id: string;
  thread_id: string;
  root_runtime_session_id: string;
  participant_id?: string | null;
  runtime_session_id?: string | null;
  runtime_turn_id?: string | null;
  runtime_event_id?: string | null;
  event_type: string;
  visibility_plane: InterAgentVisibilityPlane;
  sequence: number;
  correlation_id: string;
  idempotency_key: string;
  payload: Record<string, unknown>;
  created_at: string;
};

export type InterAgentArtifactRecord = {
  artifact_id: string;
  event_id: string;
  run_id: string;
  participant_id?: string | null;
  label: string;
  status: string;
  created_at?: string | null;
  workspace_relative_path?: string;
  relative_path?: string;
  file_id?: string;
  deep_link?: string;
  partial_output?: string;
  [key: string]: unknown;
};

export type InterAgentParticipantTranscriptItem = {
  message_id: string;
  kind: "input" | "output" | "summary" | "artifact" | "approval" | "status";
  role: "user" | "participant" | "system";
  text: string;
  status: string;
  created_at: string;
  truncated?: boolean;
};

export type InterAgentParticipantTranscriptPayload = {
  run_id: string;
  participant: {
    participant_id: string;
    label: string;
    kind: string;
    status: string;
  };
  visibility_plane: InterAgentVisibilityPlane;
  items: InterAgentParticipantTranscriptItem[];
  item_count: number;
  truncated: boolean;
};

export type InterAgentEventPage = {
  items: InterAgentEventRecord[];
  visibility_plane: InterAgentVisibilityPlane;
  limit: number;
  after_event_id?: string | null;
  before_event_id?: string | null;
  has_more_before?: boolean;
  has_more_after?: boolean;
  oldest_event_id?: string | null;
  newest_event_id?: string | null;
};

export type InterAgentArtifactPage = Omit<InterAgentEventPage, "items"> & {
  items: InterAgentArtifactRecord[];
};

export type InterAgentRunDetail = {
  run: InterAgentRunRecord;
  participants: InterAgentParticipantRecord[];
  edges: InterAgentEdgeRecord[];
  budget_policy: InterAgentBudgetPolicyRecord | null;
  budget_ledger: InterAgentBudgetLedgerRecord | null;
  final_answer?: string;
  participant_results?: Array<Record<string, unknown>>;
  root_runtime_events?: RuntimeEvent[];
  root_runtime_turn?: RuntimeTurn;
};

export type InterAgentWebSocketFrame =
  | {
      type: "inter_agent.snapshot";
      run_detail: InterAgentRunDetail;
      approvals: InterAgentApprovalRecord[];
      artifacts: InterAgentArtifactRecord[];
      events: InterAgentEventRecord[];
      visibility_plane: InterAgentVisibilityPlane;
      last_event_id: string | null;
      has_more_before?: boolean;
      oldest_event_id?: string | null;
    }
  | {
      type: "inter_agent.history.page";
      events: InterAgentEventRecord[];
      artifacts?: InterAgentArtifactRecord[];
      visibility_plane: InterAgentVisibilityPlane;
      before_event_id: string | null;
      oldest_event_id: string | null;
      newest_event_id: string | null;
      has_more_before: boolean;
      cursor_found?: boolean;
    }
  | { type: "inter_agent.event"; event: InterAgentEventRecord }
  | { type: "inter_agent.heartbeat"; run_id: string; at: string };

export type WidgetRegistryItem = {
  owner_app_id: string;
  widget_id: string;
  host: string;
  content_kinds: string[];
  frontend_mount: string;
  actions: Record<string, boolean>;
};

export type WidgetRegistryPayload = {
  items: WidgetRegistryItem[];
};

export type WidgetContextPayload = {
  context_token: string;
  context: Record<string, unknown>;
};

export type AppRegistryItem = {
  app_id: string;
  name: string;
  description: string;
  status: string;
  frontend_mount: string;
  backend_mount: string;
};

export type SkillSummary = {
  id: string;
  name: string;
  description: string;
  enabled: boolean;
};

export type RuntimeSessionOptions = {
  agent_id?: string;
  agent_role_id?: string;
  agent_type_id?: string;
  project_id?: string | null;
  system_prompt?: string;
  source_app_id?: string;
  skill_catalog_app_id?: string;
  skill_ids?: string[];
  runtime_mode?: "agentic" | "plain_hosted_chat";
  routing_profile?: "fast_model" | string;
  hosted_provider_id?: string;
  hosted_model_id?: string;
  title?: string;
};
