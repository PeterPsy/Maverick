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

function threadTimestamp(value: string | null | undefined): number {
  if (!value) {
    return 0;
  }
  const parsed = Date.parse(value);
  return Number.isFinite(parsed) ? parsed : 0;
}

export function orderChatThreads(threads: ChatThread[]): ChatThread[] {
  return threads
    .slice()
    .sort((left, right) => {
      const leftUserMessageAt = threadTimestamp(left.last_user_message_at);
      const rightUserMessageAt = threadTimestamp(right.last_user_message_at);
      const leftHasUserMessage = leftUserMessageAt > 0;
      const rightHasUserMessage = rightUserMessageAt > 0;
      if (leftHasUserMessage !== rightHasUserMessage) {
        return rightHasUserMessage ? 1 : -1;
      }
      const leftRecency = leftHasUserMessage ? leftUserMessageAt : threadTimestamp(left.created_at);
      const rightRecency = rightHasUserMessage ? rightUserMessageAt : threadTimestamp(right.created_at);
      if (leftRecency !== rightRecency) {
        return rightRecency - leftRecency;
      }
      return left.thread_id.localeCompare(right.thread_id);
    });
}

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

export class ApiError extends Error {
  path: string;
  status: number;

  constructor(message: string, { path, status }: { path: string; status: number }) {
    super(message);
    this.name = "ApiError";
    this.path = path;
    this.status = status;
  }
}

async function requestJson<T>(path: string, init: RequestInit = {}): Promise<T> {
  const response = await fetch(path, {
    credentials: "same-origin",
    ...init,
    headers: { Accept: "application/json", ...(init.headers || {}) },
  });
  if (!response.ok) {
    let detail = `Request failed ${response.status}: ${path}`;
    try {
      const payload = (await response.json()) as { error?: string };
      detail = payload.error || detail;
    } catch {
      // Keep the HTTP fallback detail.
    }
    throw new ApiError(detail, { path, status: response.status });
  }
  return (await response.json()) as T;
}

export function isRuntimeSessionUnavailableError(error: unknown, sessionId?: string): boolean {
  if (!(error instanceof ApiError)) {
    return false;
  }
  if (error.status !== 403 && error.status !== 404) {
    return false;
  }
  const runtimePathPrefix = sessionId
    ? `/api/runtime/sessions/${encodeURIComponent(sessionId)}`
    : "/api/runtime/sessions/";
  return error.path.startsWith(runtimePathPrefix);
}

export function listProviders(): Promise<ProviderPayload> {
  return requestJson<ProviderPayload>("/api/providers");
}

function stringField(value: unknown, fallback = ""): string {
  return typeof value === "string" ? value : fallback;
}

function stringArrayField(value: unknown): string[] {
  return Array.isArray(value) ? value.filter((item): item is string => typeof item === "string") : [];
}

function booleanField(value: unknown, fallback = false): boolean {
  return typeof value === "boolean" ? value : fallback;
}

function objectField(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" ? (value as Record<string, unknown>) : {};
}

export async function listApps(): Promise<AppRegistryItem[]> {
  const payload = await requestJson<{ items?: unknown[] }>("/api/apps");
  return (payload.items || [])
    .map((value) => {
      const item = value && typeof value === "object" ? (value as Record<string, unknown>) : {};
      const appId = stringField(item.app_id);
      return {
        app_id: appId,
        name: stringField(item.name, appId || "Unnamed app"),
        description: stringField(item.description),
        status: stringField(item.status, "unknown"),
        frontend_mount: stringField(item.frontend_mount),
        backend_mount: stringField(item.backend_mount),
      };
    })
    .filter((item) => item.app_id && item.status === "enabled");
}

function normalizeDependencyCandidate(value: unknown): DependencyProviderCandidate {
  const item = objectField(value);
  return {
    app_id: stringField(item.app_id),
    name: stringField(item.name),
    version: stringField(item.version),
    interface: stringField(item.interface),
    interface_version: stringField(item.interface_version),
    description: stringField(item.description),
    surfaces: stringArrayField(item.surfaces),
  };
}

function normalizeDependencyResolution(value: unknown): DependencyResolutionItem {
  const item = objectField(value);
  return {
    alias: stringField(item.alias),
    interface: stringField(item.interface),
    version: stringField(item.version),
    required: booleanField(item.required, true),
    cardinality: stringField(item.cardinality, "one"),
    description: stringField(item.description),
    status: stringField(item.status, "unknown"),
    candidates: Array.isArray(item.candidates) ? item.candidates.map(normalizeDependencyCandidate).filter((candidate) => candidate.app_id) : [],
    selected_provider_app_ids: stringArrayField(item.selected_provider_app_ids),
    stale_provider_app_ids: stringArrayField(item.stale_provider_app_ids),
    blocked_reason: item.blocked_reason === null ? null : stringField(item.blocked_reason) || null,
  };
}

export function getAppDependencies(consumerAppId: string): Promise<AppDependenciesPayload> {
  const params = new URLSearchParams({ consumer_app_id: consumerAppId });
  return requestJson<unknown>(`/api/apps/dependencies?${params.toString()}`).then((value) => {
    const payload = objectField(value);
    return {
      workspace_id: stringField(payload.workspace_id, "default"),
      consumer_app_id: stringField(payload.consumer_app_id, consumerAppId),
      status: stringField(payload.status, "unknown"),
      dependencies: Array.isArray(payload.dependencies)
        ? payload.dependencies.map(normalizeDependencyResolution).filter((item) => item.alias)
        : [],
    };
  });
}

export function selectedDependencyProviderAppId(payload: AppDependenciesPayload, alias: string): string {
  const dependency = payload.dependencies.find((item) => item.alias === alias);
  return selectedProviderIdsForDependency(dependency)[0] || "";
}

export function selectedSharedDependencyProviderAppId(payload: AppDependenciesPayload, aliases: string[]): string {
  const dependencies = aliases
    .map((alias) => payload.dependencies.find((item) => item.alias === alias))
    .filter((item): item is DependencyResolutionItem => Boolean(item));
  if (dependencies.length !== aliases.length) {
    return "";
  }
  const [primary, ...rest] = dependencies;
  for (const providerAppId of selectedProviderIdsForDependency(primary)) {
    if (rest.every((dependency) => selectedProviderIdsForDependency(dependency).includes(providerAppId))) {
      return providerAppId;
    }
  }
  return "";
}

function selectedProviderIdsForDependency(dependency: DependencyResolutionItem | undefined): string[] {
  if (!dependency) {
    return [];
  }
  const backendProviderIds = backendCandidateProviderIds(dependency);
  if (dependency.selected_provider_app_ids.length) {
    return dependency.selected_provider_app_ids.filter((providerAppId) => backendProviderIds.includes(providerAppId));
  }
  if (canUseAutomaticDependencyProvider(dependency)) {
    return backendProviderIds;
  }
  return [];
}

function canUseAutomaticDependencyProvider(dependency: DependencyResolutionItem): boolean {
  return (
    dependency.status === "optional_unset" &&
    dependency.cardinality === "one" &&
    dependency.stale_provider_app_ids.length === 0 &&
    !dependency.blocked_reason &&
    backendCandidateProviderIds(dependency).length > 0
  );
}

function backendCandidateProviderIds(dependency: DependencyResolutionItem): string[] {
  return dependency.candidates
    .filter((candidate) => candidate.surfaces.includes("backend"))
    .map((candidate) => candidate.app_id);
}

function normalizeAgentType(value: unknown): AgentTypeSummary {
  const item = objectField(value);
  return {
    id: stringField(item.id),
    name: stringField(item.name),
    description: stringField(item.description),
    role_id: stringField(item.role_id),
    skill_ids: stringArrayField(item.skill_ids),
    trace_verbosity: stringField(item.trace_verbosity, "compact"),
    enabled: item.enabled !== false,
  };
}

export function listAgentCatalog(providerAppId: string): Promise<AgentCatalogPayload> {
  return requestJson<{ workspace_id?: string; agent_types?: unknown[] }>(`/api/apps/${encodeURIComponent(providerAppId)}/backend`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ action: "catalog.compact", entity_type: "agent_type", limit: 100 }),
  }).then((payload) => ({
    workspace_id: payload.workspace_id,
    agent_types: (payload.agent_types || []).map(normalizeAgentType).filter((item) => item.id && item.enabled),
  }));
}

export function getAgentDefinition(providerAppId: string, agentTypeId: string): Promise<AgentDefinitionPayload> {
  return requestJson<AgentDefinitionPayload>(`/api/apps/${encodeURIComponent(providerAppId)}/backend`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ action: "get_agent_definition", id: agentTypeId }),
  });
}

export function previewAgentPrompt(providerAppId: string, agentTypeId: string): Promise<AgentPromptPreviewPayload> {
  return requestJson<AgentPromptPreviewPayload>(`/api/apps/${encodeURIComponent(providerAppId)}/backend`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ action: "preview_prompt", agent_type_id: agentTypeId }),
  });
}

export async function listSkills(): Promise<SkillSummary[]> {
  const payload = await requestJson<{ skills?: SkillSummary[] }>("/api/apps/skills/backend", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ action: "catalog" }),
  });
  return (payload.skills || []).filter((skill) => skill.enabled);
}

export async function searchAppReferences(
  query: string,
  signal?: AbortSignal,
  options: SearchAppReferencesOptions = {},
): Promise<AppEntityReference[]> {
  const body: Record<string, unknown> = { query, limit: options.limit || 8 };
  const appIds = (options.appIds || []).map((appId) => appId.trim()).filter(Boolean);
  const entityTypes = (options.entityTypes || []).map((entityType) => entityType.trim()).filter(Boolean);
  if (appIds.length) {
    body.app_ids = appIds;
  }
  if (entityTypes.length) {
    body.entity_types = entityTypes;
  }
  const payload = await requestJson<{ items?: AppEntityReference[] }>("/api/app-references/search", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
    signal,
  });
  return (payload.items || []).filter((item) => item.type === "entity" && item.app_id && item.entity_type && item.entity_id);
}

export function selectProvider(provider_id: string): Promise<ProviderPayload> {
  return requestJson<ProviderPayload>("/api/providers/active", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ provider_id }),
  });
}

export function createRuntimeSession(options: RuntimeSessionOptions = {}): Promise<RuntimeSession> {
  return requestJson<RuntimeSession>("/api/runtime/sessions", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      agent_id: options.agent_id || "chat",
      agent_role_id: options.agent_role_id || "",
      agent_type_id: options.agent_type_id || "",
      project_id: options.project_id || null,
      source_app_id: options.source_app_id || "chat",
      system_prompt: options.system_prompt || undefined,
      skill_catalog_app_id: options.skill_catalog_app_id || undefined,
      skill_ids: options.skill_ids || [],
      title: options.title || "New chat",
    }),
  });
}

function serializableMessageAttachments(attachments: ChatMessageAttachment[]) {
  return attachments.map(({ objectUrl: _objectUrl, ...attachment }) => attachment);
}

export function createRuntimeSessionWithTurn({
  appReferences = [],
  attachments = [],
  clientMessageId,
  inputText,
  options = {},
}: {
  appReferences?: AppReference[];
  attachments?: ChatMessageAttachment[];
  clientMessageId?: string;
  inputText: string;
  options?: RuntimeSessionOptions;
}): Promise<{
  session: RuntimeSession;
  thread?: ChatThread;
  turn: RuntimeTurn;
  events: RuntimeEvent[];
}> {
  const body: Record<string, unknown> = {
    agent_id: options.agent_id || "chat",
    agent_role_id: options.agent_role_id || "",
    agent_type_id: options.agent_type_id || "",
    project_id: options.project_id || null,
    source_app_id: options.source_app_id || "chat",
    system_prompt: options.system_prompt || undefined,
    skill_catalog_app_id: options.skill_catalog_app_id || undefined,
    skill_ids: options.skill_ids || [],
    title: options.title || "New chat",
    input_text: inputText,
    client_message_id: clientMessageId,
    attachments: serializableMessageAttachments(attachments),
    async: true,
  };
  if (appReferences.length) {
    body.app_references = appReferences;
  }
  return requestJson("/api/runtime/sessions", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

export function runtimeWebSocketUrl(sessionId: string, lastEventId?: string | null): string {
  const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
  const url = new URL(`${protocol}//${window.location.host}/ws/runtime/sessions/${encodeURIComponent(sessionId)}`);
  if (lastEventId) {
    url.searchParams.set("last_event_id", lastEventId);
  }
  return url.toString();
}

export function runtimeEventFromWebSocketFrame(frame: RuntimeWebSocketFrame): RuntimeEvent | null {
  return frame.type === "runtime.event" ? frame.event : null;
}

export function runtimeThreadWebSocketUrl(): string {
  const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
  return `${protocol}//${window.location.host}/ws/runtime/threads`;
}

export function sendRuntimeTurn(
  sessionId: string,
  inputText: string,
  clientMessageId?: string,
  attachments: ChatMessageAttachment[] = [],
  appReferences: AppReference[] = [],
): Promise<{
  session: RuntimeSession;
  thread?: ChatThread;
  turn: RuntimeTurn;
  events: RuntimeEvent[];
}> {
  const body: Record<string, unknown> = {
    input_text: inputText,
    client_message_id: clientMessageId,
    attachments: serializableMessageAttachments(attachments),
    async: true,
  };
  if (appReferences.length) {
    body.app_references = appReferences;
  }
  return requestJson(`/api/runtime/sessions/${encodeURIComponent(sessionId)}/turns`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

export function uploadWorkspaceFile(payload: {
  filename: string;
  content_type: string;
  content_base64: string;
}): Promise<{ file: UploadedWorkspaceFile }> {
  return requestJson<{ file: UploadedWorkspaceFile }>("/api/workspace-files/uploads", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

export function listWidgets(host: string, contentKind: string): Promise<WidgetRegistryPayload> {
  const query = new URLSearchParams({ host, content_kind: contentKind });
  return requestJson<WidgetRegistryPayload>(`/api/apps/widgets?${query.toString()}`);
}

export function createWidgetContext(payload: {
  host_app_id: string;
  owner_app_id: string;
  widget_id: string;
  message_id: string;
  content: StructuredContent;
}): Promise<WidgetContextPayload> {
  return requestJson<WidgetContextPayload>("/api/apps/widgets/context", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

export function getWidgetContext(contextToken: string): Promise<{ context: Record<string, unknown> }> {
  return requestJson<{ context: Record<string, unknown> }>(`/api/apps/widgets/context/${encodeURIComponent(contextToken)}`);
}

export function interruptRuntimeTurn(turnId: string): Promise<{
  turn: RuntimeTurn;
  event?: RuntimeEvent;
  interrupted: boolean;
}> {
  return requestJson(`/api/runtime/turns/${encodeURIComponent(turnId)}/interrupt`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
  });
}

export async function listChatProjects(): Promise<ChatProjectsPayload> {
  const payload = await requestJson<{ projects?: ChatProject[]; preferences?: Record<string, unknown> }>("/api/apps/chat/backend", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ action: "projects.list" }),
  });
  return { projects: payload.projects || [], preferences: payload.preferences };
}

async function withChatProjects<T extends { threads: ChatThread[] }>(payload: T): Promise<T & { projects: ChatProject[]; preferences?: Record<string, unknown> }> {
  const projectsPayload = await listChatProjects();
  return { ...payload, threads: orderChatThreads(payload.threads || []), ...projectsPayload };
}

export async function createThread(
  runtimeSessionId: string,
  projectId?: string | null,
  metadata: {
    agent_label?: string;
    agent_type_id?: string;
    agent_role_id?: string;
    source_app_id?: string;
    system_prompt?: string;
    title?: string;
  } = {},
): Promise<{ thread: ChatThread; threads: ChatThread[]; projects?: ChatProject[] }> {
  const payload = await requestJson<{ thread: ChatThread; threads: ChatThread[] }>("/api/runtime/threads", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ runtime_session_id: runtimeSessionId, project_id: projectId || null, ...metadata }),
  });
  return withChatProjects(payload);
}

export async function updateThread(payload: {
  thread_id: string;
  title?: string;
  runtime_session_id?: string;
  system_prompt?: string;
  project_id?: string | null;
  archived?: boolean;
}): Promise<{ thread: ChatThread; threads: ChatThread[]; projects?: ChatProject[] }> {
  const response = await requestJson<{ thread: ChatThread; threads: ChatThread[] }>(`/api/runtime/threads/${encodeURIComponent(payload.thread_id)}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  return withChatProjects(response);
}

export async function markThreadRead(threadId: string): Promise<{ thread: ChatThread; threads: ChatThread[]; projects?: ChatProject[] }> {
  const response = await requestJson<{ thread: ChatThread; threads: ChatThread[] }>(`/api/runtime/threads/${encodeURIComponent(threadId)}/read`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
  });
  return withChatProjects(response);
}

export async function deleteThread(threadId: string): Promise<ChatSidebarPayload> {
  const payload = await requestJson<DeleteThreadPayload>(`/api/runtime/threads/${encodeURIComponent(threadId)}`, {
    method: "DELETE",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ reason: "chat_thread_deleted" }),
  });
  return withChatProjects(payload);
}

export async function createProject(name: string): Promise<{ project: ChatProject } & ChatProjectsPayload> {
  const projectPayload = await requestJson<{ project: ChatProject; projects?: ChatProject[]; preferences?: Record<string, unknown> }>("/api/apps/chat/backend", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ action: "projects.create", name }),
  });
  return { ...projectPayload, projects: projectPayload.projects || [] };
}

export async function updateProject(projectId: string, name: string): Promise<{ project: ChatProject } & ChatProjectsPayload> {
  const projectPayload = await requestJson<{ project: ChatProject; projects?: ChatProject[]; preferences?: Record<string, unknown> }>("/api/apps/chat/backend", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ action: "projects.update", project_id: projectId, name }),
  });
  return { ...projectPayload, projects: projectPayload.projects || [] };
}

export async function deleteProject(projectId: string): Promise<ChatProjectsPayload> {
  const backendPath = "/api/apps/chat/backend";
  const projectPayload = await requestJson<{ projects?: ChatProject[]; preferences?: Record<string, unknown> }>(backendPath, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ action: "projects.delete", project_id: projectId }),
  });
  if (!Array.isArray(projectPayload.projects)) {
    throw new ApiError("Project deletion did not return updated projects.", { path: backendPath, status: 502 });
  }
  return { projects: projectPayload.projects, preferences: projectPayload.preferences };
}
