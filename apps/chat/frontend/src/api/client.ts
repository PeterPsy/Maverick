export type ProviderItem = {
  provider_id: string;
  label: string;
  description: string;
  status: string;
  default_model_family: string | null;
};

export type ProviderPayload = {
  workspace_id: string;
  active_provider: ProviderItem;
  items?: ProviderItem[];
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

export type RuntimeSession = {
  session_id: string;
  workspace_id: string;
  agent_id: string;
  status: string;
  effective_mode: string;
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
  | { type: "runtime.event"; event: RuntimeEvent }
  | { type: "runtime.replay_complete"; session_id: string; last_event_id: string | null }
  | { type: "runtime.heartbeat"; session_id: string; at: string };

export type ChatMessage = {
  id: string;
  role: "human" | "agent" | "system" | "tool" | "structured" | "step";
  content: string;
  createdAt: string;
  status?: "pending" | "failed" | "complete";
  attachments?: ChatMessageAttachment[];
  structuredContent?: StructuredContent;
  toolCall?: ToolCallMessage;
  toolCalls?: ToolCallMessage[];
  step?: RuntimeStepMessage;
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

export type RuntimeSessionOptions = {
  system_prompt?: string;
  source_app_id?: string;
  skill_ids?: string[];
};

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
    throw new Error(detail);
  }
  return (await response.json()) as T;
}

export function listProviders(): Promise<ProviderPayload> {
  return requestJson<ProviderPayload>("/api/providers");
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
      agent_id: "chat",
      source_app_id: options.source_app_id || "chat",
      system_prompt: options.system_prompt || undefined,
      skill_ids: options.skill_ids || [],
    }),
  });
}

export async function getAgentsCommonPrompt(): Promise<string> {
  const payload = await requestJson<{ common_prompt?: string }>("/api/apps/agents/backend", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ action: "get_common_prompt" }),
  });
  return (payload.common_prompt || "").trim();
}

export function getRuntimeSession(sessionId: string): Promise<RuntimeSession> {
  return requestJson<RuntimeSession>(`/api/runtime/sessions/${encodeURIComponent(sessionId)}`);
}

export function listRuntimeEvents(sessionId: string): Promise<{ items: RuntimeEvent[] }> {
  return requestJson<{ items: RuntimeEvent[] }>(`/api/runtime/sessions/${encodeURIComponent(sessionId)}/events`);
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

export function sendRuntimeTurn(
  sessionId: string,
  inputText: string,
  clientMessageId?: string,
  attachments: ChatMessageAttachment[] = [],
): Promise<{
  session: RuntimeSession;
  turn: RuntimeTurn;
  events: RuntimeEvent[];
}> {
  return requestJson(`/api/runtime/sessions/${encodeURIComponent(sessionId)}/turns`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ input_text: inputText, client_message_id: clientMessageId, attachments, async: true }),
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

export function listThreads(): Promise<ChatSidebarPayload> {
  return requestJson<ChatSidebarPayload>("/api/apps/chat/backend", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ action: "sidebar.snapshot" }),
  });
}

export function getThread(threadId: string): Promise<{ thread: ChatThread; threads: ChatThread[]; projects?: ChatProject[] }> {
  return requestJson<{ thread: ChatThread; threads: ChatThread[]; projects?: ChatProject[] }>("/api/apps/chat/backend", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ action: "threads.get", thread_id: threadId }),
  });
}

export function createThread(
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
  return requestJson<{ thread: ChatThread; threads: ChatThread[]; projects?: ChatProject[] }>("/api/apps/chat/backend", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ action: "threads.create", runtime_session_id: runtimeSessionId, project_id: projectId || null, ...metadata }),
  });
}

export function updateThread(payload: {
  thread_id: string;
  title?: string;
  runtime_session_id?: string;
  system_prompt?: string;
  project_id?: string | null;
  archived?: boolean;
}): Promise<{ thread: ChatThread; threads: ChatThread[]; projects?: ChatProject[] }> {
  return requestJson<{ thread: ChatThread; threads: ChatThread[]; projects?: ChatProject[] }>("/api/apps/chat/backend", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ action: "threads.update", ...payload }),
  });
}

export function deleteThread(threadId: string): Promise<ChatSidebarPayload> {
  return requestJson<ChatSidebarPayload>("/api/apps/chat/backend", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ action: "threads.delete", thread_id: threadId }),
  });
}

export function createProject(name: string): Promise<{ project: ChatProject } & ChatSidebarPayload> {
  return requestJson<{ project: ChatProject } & ChatSidebarPayload>("/api/apps/chat/backend", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ action: "projects.create", name }),
  });
}

export function updateProject(projectId: string, name: string): Promise<{ project: ChatProject } & ChatSidebarPayload> {
  return requestJson<{ project: ChatProject } & ChatSidebarPayload>("/api/apps/chat/backend", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ action: "projects.update", project_id: projectId, name }),
  });
}

export function deleteProject(projectId: string): Promise<ChatSidebarPayload> {
  return requestJson<ChatSidebarPayload>("/api/apps/chat/backend", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ action: "projects.delete", project_id: projectId }),
  });
}
