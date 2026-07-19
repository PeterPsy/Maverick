import { requestJson } from "./http";
import type {
  InterAgentApprovalRecord,
  InterAgentArtifactPage,
  InterAgentEventRecord,
  InterAgentEventPage,
  InterAgentParticipantTranscriptPayload,
  InterAgentRunDetail,
  InterAgentVisibilityPlane,
  InterAgentWebSocketFrame,
  MultiAgentComposerMode,
} from "./types";

export type CreateInterAgentOrchestrationPayload = {
  root_runtime_session_id: string;
  source_runtime_turn_id: string;
  policy: Exclude<MultiAgentComposerMode, "off">;
  idempotency_key: string;
};

export function createInterAgentOrchestration(
  payload: CreateInterAgentOrchestrationPayload,
  requestOptions: { signal?: AbortSignal } = {},
): Promise<InterAgentRunDetail> {
  return requestJson<InterAgentRunDetail>("/api/inter-agent/orchestrations", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    signal: requestOptions.signal,
    body: JSON.stringify(payload),
  });
}

export function sendInterAgentDirective(
  runId: string,
  payload: { text: string; idempotency_key?: string },
): Promise<{ directive: InterAgentEventRecord }> {
  return requestJson(`/api/inter-agent/runs/${encodeURIComponent(runId)}/directives`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

export function listInterAgentRuns(): Promise<{ items: InterAgentRunDetail[] }> {
  return requestJson<{ items: InterAgentRunDetail[] }>("/api/inter-agent/runs");
}

export function getInterAgentRun(runId: string): Promise<InterAgentRunDetail> {
  return requestJson<InterAgentRunDetail>(`/api/inter-agent/runs/${encodeURIComponent(runId)}`);
}

export function listInterAgentRunEvents(
  runId: string,
  options: { afterEventId?: string | null; beforeEventId?: string | null; visibilityPlane?: InterAgentVisibilityPlane; limit?: number } = {},
): Promise<InterAgentEventPage> {
  const query = new URLSearchParams();
  query.set("visibility_plane", options.visibilityPlane || "summary");
  if (options.afterEventId) {
    query.set("after_event_id", options.afterEventId);
  }
  if (options.beforeEventId) {
    query.set("before_event_id", options.beforeEventId);
  }
  if (options.limit && Number.isFinite(options.limit)) {
    query.set("limit", String(Math.max(1, Math.floor(options.limit))));
  }
  return requestJson<InterAgentEventPage>(`/api/inter-agent/runs/${encodeURIComponent(runId)}/events?${query.toString()}`);
}

export function listInterAgentRunArtifacts(
  runId: string,
  options: { afterEventId?: string | null; beforeEventId?: string | null; visibilityPlane?: InterAgentVisibilityPlane; limit?: number } = {},
): Promise<InterAgentArtifactPage> {
  const query = new URLSearchParams();
  query.set("visibility_plane", options.visibilityPlane || "detail");
  if (options.afterEventId) {
    query.set("after_event_id", options.afterEventId);
  }
  if (options.beforeEventId) {
    query.set("before_event_id", options.beforeEventId);
  }
  if (options.limit && Number.isFinite(options.limit)) {
    query.set("limit", String(Math.max(1, Math.floor(options.limit))));
  }
  return requestJson<InterAgentArtifactPage>(`/api/inter-agent/runs/${encodeURIComponent(runId)}/artifacts?${query.toString()}`);
}

export function listInterAgentRunApprovals(runId: string): Promise<{ items: InterAgentApprovalRecord[] }> {
  return requestJson<{ items: InterAgentApprovalRecord[] }>(`/api/inter-agent/runs/${encodeURIComponent(runId)}/approvals`);
}

export function getInterAgentParticipantTranscript(
  runId: string,
  participantId: string,
  options: { limit?: number } = {},
): Promise<InterAgentParticipantTranscriptPayload> {
  const query = new URLSearchParams();
  if (options.limit && Number.isFinite(options.limit)) {
    query.set("limit", String(Math.max(1, Math.floor(options.limit))));
  }
  const suffix = query.toString() ? `?${query.toString()}` : "";
  return requestJson<InterAgentParticipantTranscriptPayload>(
    `/api/inter-agent/runs/${encodeURIComponent(runId)}/participants/${encodeURIComponent(participantId)}/transcript${suffix}`,
  );
}

export function resolveInterAgentApproval(
  approvalId: string,
  payload: { approved: boolean; reason?: string },
): Promise<{ approval: InterAgentApprovalRecord }> {
  return requestJson<{ approval: InterAgentApprovalRecord }>(`/api/inter-agent/approvals/${encodeURIComponent(approvalId)}/resolve`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

export function interruptInterAgentRun(runId: string, payload: { participant_id?: string; reason?: string } = {}): Promise<{
  run: InterAgentRunDetail["run"];
  interrupted_sessions?: Array<Record<string, unknown>>;
}> {
  return requestJson(`/api/inter-agent/runs/${encodeURIComponent(runId)}/interrupt`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

export function resumeInterAgentRun(runId: string, payload: { reason?: string } = {}): Promise<InterAgentRunDetail> {
  return requestJson<InterAgentRunDetail>(`/api/inter-agent/runs/${encodeURIComponent(runId)}/resume`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

export function closeInterAgentRun(
  runId: string,
  payload: { delete_records?: boolean; reason?: string; terminal_status?: "completed" | "failed" | "cancelled" } = {},
): Promise<{
  run: InterAgentRunDetail["run"];
  participant_cleanups?: Array<Record<string, unknown>>;
  deleted?: Record<string, number> | null;
}> {
  return requestJson(`/api/inter-agent/runs/${encodeURIComponent(runId)}/close`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

export function interAgentWebSocketUrl(
  runId: string,
  options: { lastEventId?: string | null; initialEventLimit?: number; visibilityPlane?: InterAgentVisibilityPlane } = {},
): string {
  const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
  const url = new URL(`${protocol}//${window.location.host}/ws/inter-agent/runs/${encodeURIComponent(runId)}`);
  if (options.lastEventId) {
    url.searchParams.set("last_event_id", options.lastEventId);
  }
  url.searchParams.set("initial_event_limit", String(options.initialEventLimit || 240));
  url.searchParams.set("visibility_plane", options.visibilityPlane || "summary");
  return url.toString();
}

export function interAgentEventFromWebSocketFrame(frame: InterAgentWebSocketFrame): InterAgentEventRecord | null {
  return frame.type === "inter_agent.event" ? frame.event : null;
}
