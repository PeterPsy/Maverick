import { requestJson } from "./http";
import type {
  ChatMessageAttachment,
  AppReference,
  InterAgentApprovalRecord,
  InterAgentArtifactPage,
  InterAgentEventRecord,
  InterAgentEventPage,
  InterAgentRunDetail,
  InterAgentVisibilityPlane,
  InterAgentWebSocketFrame,
  RuntimeEvent,
  RuntimeTurn,
} from "./types";

export type InterAgentParticipantSpecPayload = {
  participant_id: string;
  kind: "orchestrator" | "agent" | "tool" | "human" | "system";
  execution_mode: "root_orchestrator" | "child_runtime_session" | "embedded_executor" | "human_gate" | "tool_proxy";
  label: string;
  agent_type_id?: string;
  agent_snapshot?: {
    agent_type_id: string;
    label: string;
    system_prompt: string;
    skill_ids: string[];
    skill_catalog_app_id: string;
  };
};

export type InterAgentEdgeSpecPayload = {
  source_id: string;
  target_id: string;
  kind: "delegated" | "handed_off" | "reviewed_by" | "produced" | "depends_on" | "requested_approval";
  label?: string;
};

export type CreateInterAgentRunPayload = {
  thread_id: string;
  root_runtime_session_id: string;
  mode: "manager_tools" | "sequential" | "concurrent";
  idempotency_key: string;
  visibility_level?: InterAgentVisibilityPlane;
  participants: InterAgentParticipantSpecPayload[];
  edges?: InterAgentEdgeSpecPayload[];
  budget: {
    max_participants: number;
    max_concurrent_participants: number;
    max_total_turns: number;
    max_turns_per_participant: number;
    max_tool_calls: number;
  };
};

export type ExecuteInterAgentRunPayload = {
  input_text: string;
  client_message_id?: string;
  attachments?: ChatMessageAttachment[];
  app_references?: AppReference[];
  async?: boolean;
};

export function listInterAgentRuns(): Promise<{ items: InterAgentRunDetail[] }> {
  return requestJson<{ items: InterAgentRunDetail[] }>("/api/inter-agent/runs");
}

export function getInterAgentRun(runId: string): Promise<InterAgentRunDetail> {
  return requestJson<InterAgentRunDetail>(`/api/inter-agent/runs/${encodeURIComponent(runId)}`);
}

export function createInterAgentRun(payload: CreateInterAgentRunPayload): Promise<InterAgentRunDetail> {
  return requestJson<InterAgentRunDetail>("/api/inter-agent/runs", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

export function executeInterAgentRun(
  runId: string,
  payload: ExecuteInterAgentRunPayload,
): Promise<
  InterAgentRunDetail & {
    root_runtime_events?: RuntimeEvent[];
    root_runtime_turn?: RuntimeTurn;
  }
> {
  return requestJson(`/api/inter-agent/runs/${encodeURIComponent(runId)}/execute`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      ...payload,
      attachments: payload.attachments ? serializableMessageAttachments(payload.attachments) : undefined,
    }),
  });
}

function serializableMessageAttachments(attachments: ChatMessageAttachment[]) {
  return attachments.map(({ objectUrl: _objectUrl, ...attachment }) => attachment);
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
