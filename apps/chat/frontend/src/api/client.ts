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

export type ChatMessage = {
  id: string;
  role: "human" | "agent" | "system";
  content: string;
  createdAt: string;
  status?: "pending" | "failed" | "complete";
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

export function createRuntimeSession(): Promise<RuntimeSession> {
  return requestJson<RuntimeSession>("/api/runtime/sessions", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ agent_id: "chat" }),
  });
}

export function listRuntimeEvents(sessionId: string): Promise<{ items: RuntimeEvent[] }> {
  return requestJson<{ items: RuntimeEvent[] }>(`/api/runtime/sessions/${encodeURIComponent(sessionId)}/events`);
}

export function sendRuntimeTurn(sessionId: string, inputText: string): Promise<{
  session: RuntimeSession;
  turn: RuntimeTurn;
  events: RuntimeEvent[];
}> {
  return requestJson(`/api/runtime/sessions/${encodeURIComponent(sessionId)}/turns`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ input_text: inputText }),
  });
}

export function listThreads(): Promise<{ threads: ChatThread[]; projects?: ChatProject[] }> {
  return requestJson<{ threads: ChatThread[]; projects?: ChatProject[] }>("/api/apps/chat/backend", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ action: "sidebar.snapshot" }),
  });
}

export function createThread(runtimeSessionId: string, projectId?: string | null): Promise<{ thread: ChatThread; threads: ChatThread[]; projects?: ChatProject[] }> {
  return requestJson<{ thread: ChatThread; threads: ChatThread[]; projects?: ChatProject[] }>("/api/apps/chat/backend", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ action: "threads.create", runtime_session_id: runtimeSessionId, project_id: projectId || null }),
  });
}

export function updateThread(payload: {
  thread_id: string;
  title?: string;
  runtime_session_id?: string;
  project_id?: string | null;
  archived?: boolean;
}): Promise<{ thread: ChatThread; threads: ChatThread[]; projects?: ChatProject[] }> {
  return requestJson<{ thread: ChatThread; threads: ChatThread[]; projects?: ChatProject[] }>("/api/apps/chat/backend", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ action: "threads.update", ...payload }),
  });
}
