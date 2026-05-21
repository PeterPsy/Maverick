export type ProviderItem = {
  provider_id: string;
  label: string;
  description: string;
  status: string;
  default_model_family: string | null;
};

export type ProviderPayload = {
  workspace_id: string;
  configured?: boolean;
  active_provider: ProviderItem | null;
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
      language_detection?: string;
      language_hint_supported?: boolean;
      profiles?: string[];
      inline_default_profile?: string;
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
  retention?: string;
  size_bytes?: number;
};

export type SpeechTranscribeOptions = {
  language?: string;
  profile?: string;
};

export type ChatThread = {
  thread_id: string;
  runtime_session_id: string;
  title: string;
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
  | { type: "runtime.snapshot"; session: RuntimeSession; events: RuntimeEvent[]; last_event_id: string | null }
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
  title?: string;
};
