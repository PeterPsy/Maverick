import { ApiError, requestJson } from "./http";
import type {
  AppReference,
  ChatMessageAttachment,
  ChatThread,
  RuntimeEvent,
  RuntimeSession,
  RuntimeSessionOptions,
  RuntimeThreadsPayload,
  RuntimeTurn,
  RuntimeTurnSubmitResponse,
  RuntimeWebSocketFrame,
  UploadedWorkspaceFile,
} from "./types";

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

export function createRuntimeSession(options: RuntimeSessionOptions = {}, requestOptions: { signal?: AbortSignal } = {}): Promise<RuntimeSession> {
  return requestJson<RuntimeSession>("/api/runtime/sessions", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    signal: requestOptions.signal,
    body: JSON.stringify({
      agent_id: options.agent_id || "chat",
      agent_role_id: options.agent_role_id || "",
      agent_type_id: options.agent_type_id || "",
      project_id: options.project_id || null,
      source_app_id: options.source_app_id || "chat",
      system_prompt: options.system_prompt || undefined,
      skill_catalog_app_id: options.skill_catalog_app_id || undefined,
      skill_ids: options.skill_ids || [],
      runtime_mode: options.runtime_mode || undefined,
      routing_profile: options.routing_profile || undefined,
      hosted_provider_id: options.hosted_provider_id || undefined,
      hosted_model_id: options.hosted_model_id || undefined,
      prepare_only: options.prepare_only || undefined,
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
  clientSubmissionStartedAt,
  inputText,
  options = {},
  signal,
}: {
  appReferences?: AppReference[];
  attachments?: ChatMessageAttachment[];
  clientMessageId?: string;
  clientSubmissionStartedAt?: string;
  inputText: string;
  options?: RuntimeSessionOptions;
  signal?: AbortSignal;
}): Promise<RuntimeTurnSubmitResponse> {
  const body: Record<string, unknown> = {
    agent_id: options.agent_id || "chat",
    agent_role_id: options.agent_role_id || "",
    agent_type_id: options.agent_type_id || "",
    project_id: options.project_id || null,
    source_app_id: options.source_app_id || "chat",
    system_prompt: options.system_prompt || undefined,
    skill_catalog_app_id: options.skill_catalog_app_id || undefined,
    skill_ids: options.skill_ids || [],
    runtime_mode: options.runtime_mode || undefined,
    routing_profile: options.routing_profile || undefined,
    hosted_provider_id: options.hosted_provider_id || undefined,
    hosted_model_id: options.hosted_model_id || undefined,
    title: options.title || "New chat",
    input_text: inputText,
    client_message_id: clientMessageId,
    client_submission_started_at: clientSubmissionStartedAt || undefined,
    attachments: serializableMessageAttachments(attachments),
    async: true,
  };
  if (appReferences.length) {
    body.app_references = appReferences;
  }
  return requestJson("/api/runtime/sessions", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    signal,
    body: JSON.stringify(body),
  });
}

export function runtimeWebSocketUrl(sessionId: string, lastEventId?: string | null, initialEventLimit = 500): string {
  const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
  const url = new URL(`${protocol}//${window.location.host}/ws/runtime/sessions/${encodeURIComponent(sessionId)}`);
  if (lastEventId) {
    url.searchParams.set("last_event_id", lastEventId);
  }
  url.searchParams.set("initial_event_limit", String(initialEventLimit));
  return url.toString();
}

export function runtimeEventFromWebSocketFrame(frame: RuntimeWebSocketFrame): RuntimeEvent | null {
  return frame.type === "runtime.event" ? frame.event : null;
}

export function runtimeThreadWebSocketUrl(): string {
  const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
  return `${protocol}//${window.location.host}/ws/runtime/threads`;
}

export function listRuntimeThreads(options: { cursor?: string | null; limit?: number; query?: string; signal?: AbortSignal } = {}): Promise<RuntimeThreadsPayload> {
  const query = new URLSearchParams();
  const searchQuery = (options.query || "").trim();
  if (searchQuery) {
    query.set("query", searchQuery);
  }
  const cursor = (options.cursor || "").trim();
  if (cursor) {
    query.set("cursor", cursor);
  }
  if (options.limit && Number.isFinite(options.limit)) {
    query.set("limit", String(Math.max(1, Math.floor(options.limit))));
  }
  const suffix = query.toString() ? `?${query.toString()}` : "";
  return requestJson<RuntimeThreadsPayload>(`/api/runtime/threads${suffix}`, {
    signal: options.signal,
  });
}

export async function getRuntimeThread(threadId: string, options: { signal?: AbortSignal } = {}): Promise<ChatThread> {
  const payload = await requestJson<{ thread: ChatThread }>(`/api/runtime/threads/${encodeURIComponent(threadId)}`, {
    signal: options.signal,
  });
  return payload.thread;
}

export function listRuntimeSessionEvents(
  sessionId: string,
  options: { limit?: number; signal?: AbortSignal } = {},
): Promise<{ items: RuntimeEvent[] }> {
  const query = new URLSearchParams();
  if (options.limit && Number.isFinite(options.limit)) {
    query.set("limit", String(Math.max(1, Math.floor(options.limit))));
  }
  const suffix = query.toString() ? `?${query.toString()}` : "";
  return requestJson<{ items: RuntimeEvent[] }>(`/api/runtime/sessions/${encodeURIComponent(sessionId)}/events${suffix}`, {
    signal: options.signal,
  });
}

export function sendRuntimeTurn(
  sessionId: string,
  inputText: string,
  clientMessageId?: string,
  attachments: ChatMessageAttachment[] = [],
  appReferences: AppReference[] = [],
  requestOptions: { signal?: AbortSignal; clientSubmissionStartedAt?: string } = {},
): Promise<RuntimeTurnSubmitResponse> {
  const body: Record<string, unknown> = {
    input_text: inputText,
    client_message_id: clientMessageId,
    client_submission_started_at: requestOptions.clientSubmissionStartedAt || undefined,
    attachments: serializableMessageAttachments(attachments),
    async: true,
  };
  if (appReferences.length) {
    body.app_references = appReferences;
  }
  return requestJson(`/api/runtime/sessions/${encodeURIComponent(sessionId)}/turns`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    signal: requestOptions.signal,
    body: JSON.stringify(body),
  });
}

export function prepareRuntimeSessionAppReferences(
  sessionId: string,
  appReferences: AppReference[] = [],
  requestOptions: { signal?: AbortSignal } = {},
): Promise<{
  session_id: string;
  status: "ready";
  reference_count: number;
  materialized_reference_count: number;
  reference_cache_hit: boolean;
  reference_fingerprint: string;
}> {
  return requestJson(`/api/runtime/sessions/${encodeURIComponent(sessionId)}/app-references/prepare`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    signal: requestOptions.signal,
    body: JSON.stringify({ app_references: appReferences }),
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

export function interruptRuntimeTurn(turnId: string): Promise<{
  turn: RuntimeTurn;
  event?: RuntimeEvent;
  inter_agent_cleanup?: Array<Record<string, unknown>>;
  interrupted: boolean;
}> {
  return requestJson(`/api/runtime/turns/${encodeURIComponent(turnId)}/interrupt`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
  });
}
