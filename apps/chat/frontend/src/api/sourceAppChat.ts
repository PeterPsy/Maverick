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
