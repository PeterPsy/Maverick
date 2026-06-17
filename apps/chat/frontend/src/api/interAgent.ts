import { requestJson } from "./http";
import type {
  ChatMessageAttachment,
  AppReference,
  InterAgentApprovalRecord,
  InterAgentEventRecord,
  InterAgentRunDetail,
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

export type CreateInterAgentRunPayload = {
  thread_id: string;
  root_runtime_session_id: string;
  mode: "manager_tools" | "sequential" | "concurrent";
  idempotency_key: string;
  participants: InterAgentParticipantSpecPayload[];
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
  options: { visibilityPlane?: "summary" | "detail" | "debug"; limit?: number } = {},
): Promise<{ items: InterAgentEventRecord[] }> {
  const query = new URLSearchParams();
  query.set("visibility_plane", options.visibilityPlane || "summary");
  if (options.limit && Number.isFinite(options.limit)) {
    query.set("limit", String(Math.max(1, Math.floor(options.limit))));
  }
  return requestJson<{ items: InterAgentEventRecord[] }>(`/api/inter-agent/runs/${encodeURIComponent(runId)}/events?${query.toString()}`);
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
