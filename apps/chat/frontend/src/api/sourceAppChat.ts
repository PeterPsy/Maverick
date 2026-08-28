import { requestJson } from "./http";
import { getRuntimeThread, listRuntimeSessionEvents } from "./runtime";
import type {
  AppReference,
  ChatMessageAttachment,
  RuntimeEvent,
  RuntimeSession,
  RuntimeTurn,
  RuntimeTurnSubmitResponse,
} from "./types";

export type SourceAppChatMode = "chat" | "plan" | "design";

export type SourceAppChatCapabilities = {
  label?: string;
  modes?: SourceAppChatMode[];
  source_app_id?: string;
  supports_design_systems?: boolean;
  supports_project_selection?: boolean;
  supports_skill_invocations?: boolean;
};

export type SourceAppChatProject = {
  id: string;
  name: string;
  design_system_id?: string | null;
};

export type SourceAppDesignSystem = {
  id: string;
  title: string;
  source?: string;
  status?: string;
  is_editable?: boolean;
};

export type SourceAppChatContext = {
  source_app_id?: string;
  od_project_id: string;
  project: SourceAppChatProject | null;
  projects: SourceAppChatProject[];
  selection_source?: "automatic" | "empty" | "workspace";
  design_systems: SourceAppDesignSystem[];
};

type RuntimeRequestResult = {
  status?: string;
  error?: string;
  interrupted?: boolean;
  runtime_session_id?: string;
  turn_id?: string;
};

type SourceAppBackendResult = {
  json?: Record<string, unknown>;
  runtime_request_results?: RuntimeRequestResult[];
};

export async function sendSourceAppTurn({
  appReferences,
  attachments,
  clientMessageId,
  inputText,
  invokedSkillIds,
  mode,
  projectId,
  runtimeSessionId,
  signal,
  sourceAppId,
}: {
  appReferences: AppReference[];
  attachments: ChatMessageAttachment[];
  clientMessageId: string;
  inputText: string;
  invokedSkillIds?: string[];
  mode: SourceAppChatMode;
  projectId: string;
  runtimeSessionId?: string;
  signal?: AbortSignal;
  sourceAppId: string;
}): Promise<RuntimeTurnSubmitResponse> {
  const payload = await requestJson<SourceAppBackendResult>(`/api/apps/${encodeURIComponent(sourceAppId)}/backend`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    signal,
    body: JSON.stringify({
      action: "chat.submit_turn",
      arguments: {
        app_references: appReferences,
        attachments: attachments.map(({ objectUrl: _objectUrl, ...attachment }) => attachment),
        client_message_id: clientMessageId,
        input_text: inputText,
        invoked_skill_ids: invokedSkillIds || [],
        project_id: projectId,
        runtime_session_id: runtimeSessionId || undefined,
        session_mode: mode,
      },
    }),
  });
  const result = payload.runtime_request_results?.[0];
  if (!result || result.status !== "submitted" || !result.runtime_session_id || !result.turn_id) {
    throw new Error(result?.error || "The source app did not create a runtime turn.");
  }
  const [session, turn, thread, events] = await Promise.all([
    getRuntimeSession(result.runtime_session_id, { signal }),
    getRuntimeTurn(result.turn_id, { signal }),
    getRuntimeThread(result.runtime_session_id, { signal }),
    listRuntimeSessionEvents(result.runtime_session_id, { limit: 500, signal }),
  ]);
  return { session, thread, turn, events: events.items };
}

export function getSourceAppChatCapabilities(
  sourceAppId: string,
  options: { signal?: AbortSignal } = {},
): Promise<SourceAppChatCapabilities> {
  return requestJson<SourceAppChatCapabilities>(`/api/apps/${encodeURIComponent(sourceAppId)}/backend`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    signal: options.signal,
    body: JSON.stringify({ action: "chat.capabilities" }),
  });
}

export function getSourceAppChatContext(
  sourceAppId: string,
  projectId = "",
  options: { signal?: AbortSignal } = {},
): Promise<SourceAppChatContext> {
  return requestJson<SourceAppChatContext>(`/api/apps/${encodeURIComponent(sourceAppId)}/backend`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    signal: options.signal,
    body: JSON.stringify({
      action: "chat.context",
      arguments: projectId ? { project_id: projectId } : {},
    }),
  });
}

export async function resolveSourceAppChatProject(
  sourceAppId: string,
  projectId = "",
  options: { signal?: AbortSignal } = {},
): Promise<string> {
  const payload = await requestJson<{ od_project_id?: string }>(
    `/api/apps/${encodeURIComponent(sourceAppId)}/backend`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      signal: options.signal,
      body: JSON.stringify({
        action: "chat.resolve_project",
        arguments: projectId ? { project_id: projectId } : {},
      }),
    },
  );
  return typeof payload.od_project_id === "string" ? payload.od_project_id : "";
}

export function setSourceAppChatDesignSystem({
  designSystemId,
  projectId,
  signal,
  sourceAppId,
}: {
  designSystemId: string | null;
  projectId: string;
  signal?: AbortSignal;
  sourceAppId: string;
}): Promise<{ od_project_id: string; project: SourceAppChatProject }> {
  return requestJson<{ od_project_id: string; project: SourceAppChatProject }>(
    `/api/apps/${encodeURIComponent(sourceAppId)}/backend`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      signal,
      body: JSON.stringify({
        action: "chat.set_design_system",
        arguments: {
          design_system_id: designSystemId,
          project_id: projectId,
        },
      }),
    },
  );
}

export async function cancelSourceAppTurn({
  runtimeSessionId,
  sourceAppId,
  turnId,
}: {
  runtimeSessionId: string;
  sourceAppId: string;
  turnId: string;
}): Promise<{ turn: RuntimeTurn; event?: RuntimeEvent; interrupted: boolean }> {
  const payload = await requestJson<SourceAppBackendResult>(`/api/apps/${encodeURIComponent(sourceAppId)}/backend`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      action: "chat.cancel_turn",
      arguments: { runtime_session_id: runtimeSessionId, turn_id: turnId },
    }),
  });
  const result = payload.runtime_request_results?.[0];
  if (!result || result.status !== "cancelled") {
    throw new Error(result?.error || "The source app did not stop the runtime turn.");
  }
  const [turn, events] = await Promise.all([
    getRuntimeTurn(turnId),
    listRuntimeSessionEvents(runtimeSessionId, { limit: 500 }),
  ]);
  return { turn, event: events.items.at(-1), interrupted: true };
}

export function getRuntimeSession(sessionId: string, options: { signal?: AbortSignal } = {}): Promise<RuntimeSession> {
  return requestJson<RuntimeSession>(`/api/runtime/sessions/${encodeURIComponent(sessionId)}`, { signal: options.signal });
}

export function getRuntimeTurn(turnId: string, options: { signal?: AbortSignal } = {}): Promise<RuntimeTurn> {
  return requestJson<RuntimeTurn>(`/api/runtime/turns/${encodeURIComponent(turnId)}`, { signal: options.signal });
}
