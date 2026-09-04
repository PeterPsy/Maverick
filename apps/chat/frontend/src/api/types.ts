export type AgenticDataDestination = {
  provider_id: string;
  endpoint_id: string;
  upstream_provider_ids: string[];
  display_label: string;
};

export type AgenticEgressPolicy = {
  policy_id: string;
  revision: string;
  allowed_remote_data_classes: string[];
};

export type AgenticDataPolicy = {
  collection: string;
  require_zdr: boolean;
  retention?: string;
  attestation_state: "not_attested" | "active" | "revoked" | "invalid";
  attestation: {
    state: "not_attested" | "active" | "revoked" | "invalid";
    authoritative: boolean;
    declaration: "fake_data_only" | null;
    scope: {
      type: "workspace" | "resource_prefixes";
      resource_prefixes: string[];
    } | null;
    revision: number | null;
    updated_at: string | null;
    attested_at?: string;
    revoked_at?: string | null;
  };
};

export type AgenticCertificatePosture = {
  certificate_id: string;
  effective_status: string;
  eligibility: string;
  expires_at: string | null;
  pinned_evidence_digest: string;
};

export type AgenticEffectiveCapabilities = {
  status: "active" | "blocked";
  reason_code: string | null;
  snapshot_digest: string;
  computed_at?: string;
  execution_mode?: "sandbox" | "full-access";
  capabilities: {
    streaming: boolean;
    tool_orchestration: boolean;
    cli: boolean;
    mcp: boolean;
    skill_catalog: boolean;
    filesystem_list: boolean;
    filesystem_read: boolean;
    filesystem_write: boolean;
    shell: boolean;
    interrupt: boolean;
    same_turn_steering: boolean;
    recovery: boolean;
    confirmation_resume: boolean;
    provider_private_state: boolean;
    attachment_modalities: string[];
    app_references: boolean;
    confirmations: boolean;
  };
  provider?: {
    provider_id?: string;
    model_id?: string;
    protocol?: string;
    certified_upstream_ids?: string[];
    effective_upstream_ids?: string[];
    health_status?: string;
    health_revision?: string;
  };
  data_policy?: {
    allowed_remote_data_classes?: string[];
    collection?: string;
    require_zdr?: boolean;
  };
  certificate?: {
    certificate_id?: string;
    suite_id?: string;
    suite_version?: string;
    expires_at?: string | null;
  };
  tcb?: {
    posture?: string;
    [key: string]: unknown;
  };
  allowed_tool_handles?: string[];
};

export type AgenticSessionGovernance = {
  display_name: string | null;
  profile_definition_id: string;
  profile_definition_revision: string;
  workspace_binding_id: string;
  workspace_binding_revision: number;
  runtime_engine_id: string;
  execution_family?: "native_agent" | "maverick_agent" | null;
  execution_family_projection?: {
    stored_value: string | null;
    legacy_identity_projected: boolean;
  };
  full_workspace_status?: "certified" | "unavailable";
  full_workspace_contract_revision?: string | null;
  harness_recipe?: AgenticHarnessRecipe;
  model_provider_id: string;
  model_id: string;
  rollout_status: string | null;
  containment: {
    status: "GO" | "NO-GO";
    reason_code: string | null;
  };
  data_destination: AgenticDataDestination;
  egress_policy: AgenticEgressPolicy;
  data_policy: AgenticDataPolicy;
  certificate_posture: AgenticCertificatePosture;
  effective_capabilities: AgenticEffectiveCapabilities;
};

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
  workspace_profile_binding_id?: string;
  agentic_rollout_status?: string | null;
  agentic_certificate_status?: string | null;
  agentic_certificate_expires_at?: string | null;
  agentic_egress_policy_id?: string | null;
  agentic_allowed_tool_handles?: string[];
  agentic_max_estimated_cost_microusd?: number | null;
  agentic_containment_status?: "GO" | "NO-GO";
  agentic_containment_reason?: string | null;
  agentic_data_destination?: AgenticDataDestination | null;
  agentic_egress_policy?: AgenticEgressPolicy | null;
  agentic_data_policy?: AgenticDataPolicy | null;
  agentic_certificate_posture?: AgenticCertificatePosture | null;
  agentic_effective_capabilities?: AgenticEffectiveCapabilities | null;
  default_reasoning_effort?: string | null;
  supported_reasoning_efforts?: ProviderReasoningOption[];
  input_modalities?: string[];
  output_modalities?: string[];
  execution_family?: ExecutionFamilyId;
  execution_family_label?: string;
  execution_family_description?: string;
  execution_family_order?: number;
  selectable?: boolean;
  unavailable_reason?: string | null;
  full_workspace_status?: "certified" | "unavailable";
  full_workspace_contract_revision?: string | null;
  harness_recipe?: AgenticHarnessRecipe | null;
  provider_detail?: string | null;
  profile_detail?: string | null;
  legacy_selection_ids?: string[];
  hosted_text_profile?: HostedTextProfileItem | null;
};

export type ExecutionFamilyId = "native_agent" | "maverick_agent" | "hosted_text";

export type ExecutionFamilyItem = {
  family_id: ExecutionFamilyId;
  label: string;
  description: string;
  workspace_actions: boolean;
};

export type AgenticHarnessRecipe = {
  id?: string | null;
  revision?: string | null;
  digest?: string | null;
  provider_capability_catalog_digest?: string | null;
};

export type HostedTextProfileItem = {
  profile: {
    profile_id: string;
    revision: string;
    display_name: string;
    execution_family: "hosted_text";
    provider_id: string;
    model_id: string;
    model_revision: string | null;
    model_revision_policy: "exact" | "provider_alias";
    provider_protocol: string;
    provider_api_version: string | null;
    endpoint_id: string;
    input_modalities: string[];
    output_modalities: string[];
    context_limit_tokens: number | null;
    output_limit_tokens: number | null;
    cost_policy: string;
    retention_policy: string;
    data_destination: string;
  };
  status: {
    status: "available" | "disabled" | "unavailable";
    reason_code: string | null;
  };
  certificate: {
    certificate_id: string;
    certificate_kind: "hosted_text_capability";
    workspace_tools: false;
    action_loop: false;
    workspace_actions: false;
  };
  provider: { provider_id: string; label: string; status: string };
  cost?: Record<string, unknown>;
  selectable: boolean;
  unavailable_reason: string | null;
  workspace_actions_message: string;
};

export type NativeAgentItem = {
  runtime_engine_id: string;
  label: string;
  description: string;
  execution_family: "native_agent";
  provider_status: string;
  availability: "installed" | "not_installed" | "unknown";
  installed: boolean;
  executable_name: string | null;
  runtime_version: string | null;
  health: string;
  health_reason_codes: string[];
  update: { status: string; detail: string | null };
  adapter: { id: string; version: string; trusted_distribution: string };
  harness_recipe: AgenticHarnessRecipe;
  protocol: { kind: string; id: string; version: string | null; event_schema: string };
  authentication_status: string;
  models: Array<{
    provider_id: string;
    model_id: string;
    model_revision: string | null;
    model_revision_policy: string;
  }>;
  effects: {
    mode: string;
    workspace_confined: boolean;
    process_tree_supervised: boolean;
    structured_effect_events: boolean;
    sandbox_policy_revision: string;
    approval_policy: string;
  };
  certification_state: string;
  full_workspace_status: "certified" | "unavailable";
  full_workspace_contract_revision: string | null;
  selectable: boolean;
  unavailable_reason: string | null;
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
  default_reasoning_effort?: string | null;
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
  profiles?: HostedTextProfileItem[];
  workspace_actions_message?: string;
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
  execution_families?: ExecutionFamilyItem[];
  configured?: boolean;
  active_provider: ProviderItem | null;
  hosted_text?: HostedTextProviderStatus | null;
  blocked_reason?: string | null;
  blocked_detail?: string | null;
  items?: ProviderItem[];
  available_providers?: ProviderItem[];
  agentic_profiles?: {
    default_binding_id: string | null;
    items: AgenticProfileItem[];
  } | null;
  native_agents?: { items: NativeAgentItem[] } | null;
  selection_migration?: {
    schema_version: string;
    mode: "projection_only";
    persisted_records_mutated: false;
    pinned_sessions_rewritten: false;
    records: Array<{
      source_kind: string;
      source_profile: string;
      source_id: string;
      execution_family: ExecutionFamilyId | null;
      canonical_selection_id: string | null;
      storage_action: "preserved";
    }>;
  };
};

export type AgenticProfileItem = {
  workspace_profile_binding_id: string;
  definition_id: string;
  definition_revision: string;
  display_name: string;
  runtime_engine_id: string;
  model_provider_id: string;
  model_id: string;
  model_revision?: string | null;
  model_revision_policy?: string;
  default_reasoning_effort?: string | null;
  supported_reasoning_efforts?: ProviderReasoningOption[];
  rollout_status: string | null;
  enabled: boolean;
  is_default: boolean;
  selectable?: boolean;
  unavailable_reason?: string | null;
  execution_family?: "native_agent" | "maverick_agent" | null;
  family_contract_status?: string;
  family_contract_reason?: string | null;
  full_workspace_status?: "certified" | "unavailable";
  full_workspace_contract_revision?: string | null;
  harness_recipe?: AgenticHarnessRecipe;
  containment_status?: "GO" | "NO-GO";
  containment_reason?: string | null;
  certificate_eligibility?: string;
  certified?: boolean;
  provider_protocol?: string;
  provider_api_version?: string | null;
  adapter_id?: string;
  adapter_version_constraint?: string;
  egress_policy_id?: string;
  data_destination?: AgenticDataDestination;
  egress_policy?: AgenticEgressPolicy;
  data_policy?: AgenticDataPolicy;
  allowed_tool_handles?: string[];
  max_estimated_cost_microusd?: number | null;
  effective_capabilities?: AgenticEffectiveCapabilities;
  certificate?: {
    effective_status?: string;
    expires_at?: string;
  } | null;
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
  skill_activation_mode?: "implicit" | "explicit";
  trace_verbosity: string;
  enabled: boolean;
};

export type AgentCatalogPayload = {
  workspace_id?: string;
  agent_types: AgentTypeSummary[];
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
      engine?: string;
      content_types?: string[];
      max_text_chars?: number;
      voices?: Array<{ voice_id?: string; language?: string; name?: string; gender?: string }>;
      default_voice?: string;
      language_preference?: string;
      language_hint_supported?: boolean;
      languages?: string[];
      quality_profile?: string;
      latency_profile?: string;
      prewarm_supported?: boolean;
      streaming_content_type?: string;
      streaming_supported?: boolean;
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
      conversation_streaming_supported?: boolean;
      chunked_dictation_supported?: boolean;
      dictation_streaming_supported?: boolean;
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
  engine?: string;
  voice?: string;
  language?: string;
  cache_hit?: boolean;
  metrics?: { engine_seconds?: number; request_total_seconds?: number };
};

export type SpeechSynthesizeOptions = {
  language?: string;
  signal?: AbortSignal;
  voice?: string;
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
  conversation?: boolean;
  final?: boolean;
  dictation?: boolean;
};

export type ChatThreadSummary = {
  thread_id: string;
  runtime_session_id: string;
  title: string;
  title_pending?: boolean;
  agent_label: string;
  agent_type_id: string;
  agent_role_id: string;
  source_app_id: string;
  project_id: string | null;
  archived: boolean;
  availability: string;
  created_at: string;
  updated_at: string;
  last_user_message_at?: string | null;
  last_completed_response_at?: string | null;
  has_unread_completed_response?: boolean;
};

export type ChatThread = ChatThreadSummary & {
  title_source?: string;
  title_generation_failure?: string | null;
  system_prompt?: string;
  last_completed_turn_id?: string | null;
  runtime_mode?: "agentic" | "plain_hosted_chat" | string;
  provider_id?: string | null;
  hosted_provider_id?: string | null;
  hosted_model_id?: string | null;
};

export type ChatProject = {
  project_id: string;
  name: string;
  created_at: string;
  updated_at: string;
};

export type RuntimeThreadsPage = {
  items?: ChatThread[];
  limit: number;
  has_more: boolean;
  cursor: string | null;
  cursor_found?: boolean;
  sort: string;
  query?: string | null;
  total?: number;
  filtered_total?: number;
};

export type ChatSidebarPayload = {
  threads?: ChatThread[];
  changed_thread?: ChatThread;
  removed_thread_id?: string;
  deleted_thread_id?: string;
  deleted_thread_ids?: string[];
  threads_page?: RuntimeThreadsPage;
  projects?: ChatProject[];
  preferences?: Record<string, unknown>;
};

export type RuntimeThreadsPayload = {
  workspace_id?: string;
  threads: ChatThread[];
  threads_page?: RuntimeThreadsPage;
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
  runtime_root_purge_pending?: boolean;
};

export type DeleteThreadPayload = ChatSidebarPayload & {
  deleted_runtime_session_id?: string;
  runtime_cleanup?: RuntimeCleanup;
};

export type DeleteThreadsPayload = ChatSidebarPayload & {
  deleted_runtime_session_ids: string[];
  results: Array<{
    thread_id: string;
    runtime_session_id?: string;
    status: "deleted" | "not_found";
  }>;
  runtime_cleanup_batch?: {
    requested_session_ids: string[];
    expanded_session_ids: string[];
    session_results: RuntimeCleanup[];
    timings_ms: Record<string, number>;
  };
};

export type RuntimeSession = {
  session_id: string;
  workspace_id: string;
  agent_id: string;
  status: string;
  effective_mode: string;
  runtime_mode?: "agentic" | "plain_hosted_chat" | string;
  skill_ids?: string[];
  skill_catalog_app_id?: string | null;
  skill_activation_mode?: "implicit" | "explicit" | string;
  provider_id?: string;
  execution_binding?: {
    profile_definition_id?: string;
    profile_definition_revision?: string;
    workspace_binding_id: string;
    workspace_binding_revision?: number;
    capability_certificate_id?: string;
    model_id: string;
    reasoning_effort?: string | null;
    runtime_engine_id: string;
    adapter_id?: string;
    adapter_version?: string;
    model_provider_id?: string;
    provider_protocol?: string;
    provider_api_version?: string | null;
    egress_policy_id?: string;
    binding_digest: string;
  } | null;
  hosted_provider_id?: string | null;
  hosted_model_id?: string | null;
  prewarm_status?: string;
  prewarm_completed?: boolean;
  provider_thread_ready?: boolean;
  runtime_ready?: boolean;
  prewarm_total_ms?: number;
  recovery_reason_code?: string | null;
  agentic_containment?: {
    status: "GO" | "NO-GO";
    reason_code: string | null;
  } | null;
  agentic_governance?: AgenticSessionGovernance | null;
  predecessor_session_id?: string | null;
  lineage_root_session_id?: string | null;
  continuation_successor_session_id?: string | null;
  runtime_admission?: RuntimeAdmission | null;
};

export type RuntimeAdmission = {
  status: "direct" | "compatible_upgrade" | "upgrade_required" | "provider_thread_missing";
  reason_code: string | null;
  detail_code: string | null;
  source_profile_revision: string | null;
  target_profile_revision: string | null;
  provider_thread_available: boolean;
};

export type RuntimeTurn = {
  turn_id: string;
  session_id: string;
  workspace_id: string;
  status: string;
  input_text: string | null;
  client_message_id?: string | null;
  invoked_skill_ids?: string[];
  failure_reason: string | null;
  runtime_mode?: "agentic" | "plain_hosted_chat" | string;
  created_at: string;
  updated_at: string;
};

export type RuntimeTurnIdempotency = {
  status: "pending" | string;
  client_message_id: string;
  session_id: string;
  turn_id: string;
};

export type RuntimeTurnSubmitResponse = {
  session?: RuntimeSession;
  thread?: ChatThread;
  turn?: RuntimeTurn;
  events?: RuntimeEvent[];
  idempotency?: RuntimeTurnIdempotency;
  delivery?: "steered" | "queued" | "delivery_uncertain" | string;
};

export type RuntimeTurnClientMetrics = {
  attachment_upload_ms?: number;
  attachment_upload_ready_before_submit?: boolean;
  attachment_upload_wait_on_submit_ms?: number;
  prepare_refs_wait_on_submit_ms?: number;
  prepared_session_ready_before_submit?: boolean;
  prepared_session_wait_on_submit_ms?: number;
  submit_post_ms?: number;
};

export type RuntimeEvent = {
  event_id: string;
  session_id: string;
  turn_id: string | null;
  event_type: string;
  payload: Record<string, unknown>;
  created_at: string;
};

export type TokenUsageBreakdown = {
  input_tokens: number;
  cached_input_tokens: number;
  cache_write_input_tokens: number;
  output_tokens: number;
  reasoning_output_tokens: number;
  total_tokens: number;
};

export type ChatUsageSummary = {
  workspace_id: string;
  root_session_id: string;
  tokens: TokenUsageBreakdown;
  direct_tokens: TokenUsageBreakdown;
  delegated_tokens: TokenUsageBreakdown;
  context_tokens: number | null;
  context_window_tokens: number | null;
  context_used_percent: number | null;
  token_accuracy: "exact" | "estimated" | "unavailable";
  context_accuracy: "exact" | "estimated" | "unavailable";
  provider_ids: string[];
  model_ids: string[];
  estimated_cost_microusd: number | null;
  sample_count: number;
  coverage_since: string | null;
  updated_at: string | null;
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
      usage?: ChatUsageSummary | null;
      runtime_admission?: RuntimeAdmission | null;
      requested_session_id?: string | null;
      lineage_session_ids?: string[];
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
  | { type: "runtime.thread.snapshot"; workspace_id: string; threads: ChatThread[]; threads_page?: RuntimeThreadsPage; at: string }
  | {
      type: "runtime.thread.changed";
      workspace_id: string;
      action: string;
      threads?: ChatThread[];
      threads_page?: RuntimeThreadsPage;
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
  failureReasonCode?: string;
  attachments?: ChatMessageAttachment[];
  appReferences?: AppReference[];
  structuredContent?: StructuredContent;
  toolCall?: ToolCallMessage;
  toolCalls?: ToolCallMessage[];
  step?: RuntimeStepMessage;
  sourceLabel?: string;
  sourceParticipantId?: string;
  sourceRunId?: string;
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
  metadata?: Record<string, unknown>;
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
  isAudio?: boolean;
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
  status: "started" | "updated" | "awaiting_confirmation" | "completed" | "failed";
  detail: Record<string, unknown>;
  createdAt?: string;
};

export type RuntimeToolConfirmation = {
  turn_id: string;
  turn_status: string;
  confirmation_deadline_at?: string | null;
  invocation: {
    invocation_id: string;
    tool_handle: string;
    effect_class: string;
    arguments_summary: Record<string, unknown>;
    arguments_digest: string;
    state: string;
    revision: number;
    policy_revision: string;
  };
  confirmation: {
    state: string;
    expires_at: string;
    revision: number;
  } | null;
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
  source_runtime_turn_id?: string | null;
  source_app_id: string;
  mode: string;
  orchestration_policy?: string | null;
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
  kind: "input" | "output" | "summary" | "tool" | "artifact" | "approval" | "status";
  role: "user" | "participant" | "tool" | "system";
  text: string;
  status: string;
  created_at: string;
  truncated?: boolean;
  tool_call?: {
    id: string;
    name: string;
    status: "started" | "updated" | "completed" | "failed";
    detail: Record<string, unknown>;
  };
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
  skill_activation_mode?: "implicit" | "explicit";
  runtime_mode?: "agentic" | "plain_hosted_chat";
  routing_profile?: "fast_model" | string;
  hosted_provider_id?: string;
  hosted_model_id?: string;
  workspace_profile_binding_id?: string;
  reasoning_effort?: string;
  prepare_only?: boolean;
  title?: string;
};
