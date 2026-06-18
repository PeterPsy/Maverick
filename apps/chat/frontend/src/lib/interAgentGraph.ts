import type {
  InterAgentApprovalRecord,
  InterAgentArtifactRecord,
  InterAgentEventRecord,
  InterAgentRunDetail,
} from "../api/client";

export type InterAgentGraphSelection =
  | { id: string; kind: "participant"; participantId: string }
  | { id: string; kind: "edge"; edgeId: string }
  | { id: string; kind: "event"; eventId: string }
  | { id: string; kind: "artifact"; artifactId: string }
  | { id: string; kind: "approval"; approvalId: string };

export function mergeInterAgentEvents(current: InterAgentEventRecord[], incoming: InterAgentEventRecord[]): InterAgentEventRecord[] {
  if (!incoming.length) {
    return current;
  }
  const byId = new Map<string, InterAgentEventRecord>();
  for (const event of [...current, ...incoming]) {
    byId.set(event.event_id, event);
  }
  return Array.from(byId.values()).sort(interAgentEventSort);
}

export function mergeInterAgentArtifacts(
  current: InterAgentArtifactRecord[],
  incoming: InterAgentArtifactRecord[],
): InterAgentArtifactRecord[] {
  if (!incoming.length) {
    return current;
  }
  const byId = new Map<string, InterAgentArtifactRecord>();
  for (const artifact of [...current, ...incoming]) {
    byId.set(artifact.artifact_id || `${artifact.event_id}:${artifact.label}`, artifact);
  }
  return Array.from(byId.values()).sort((left, right) => String(left.created_at || "").localeCompare(String(right.created_at || "")));
}

export function artifactsFromInterAgentEvents(events: InterAgentEventRecord[]): InterAgentArtifactRecord[] {
  const artifacts: InterAgentArtifactRecord[] = [];
  for (const event of events) {
    if (event.event_type !== "inter_agent.artifact.created") {
      continue;
    }
    const refs = Array.isArray(event.payload.artifact_refs) ? event.payload.artifact_refs : [];
    refs.forEach((ref, index) => {
      if (!isRecord(ref)) {
        return;
      }
      const artifact = ref as Partial<InterAgentArtifactRecord>;
      const artifactId =
        stringField(artifact.artifact_id) ||
        stringField(artifact.file_id) ||
        stringField(artifact.workspace_relative_path) ||
        stringField(artifact.relative_path) ||
        `${event.event_id}:${index}`;
      const label =
        stringField(artifact.label) ||
        stringField(artifact.name) ||
        stringField(artifact.filename) ||
        stringField(artifact.workspace_relative_path) ||
        stringField(artifact.relative_path) ||
        `Artifact ${index + 1}`;
      artifacts.push({
        ...artifact,
        artifact_id: artifactId,
        event_id: event.event_id,
        run_id: event.run_id,
        participant_id: event.participant_id,
        label,
        status: String(event.payload.status || artifact.status || "created"),
        created_at: event.created_at,
        partial_output: typeof event.payload.partial_output === "string" ? event.payload.partial_output : artifact.partial_output,
      });
    });
  }
  return artifacts;
}

export function lastInterAgentEventId(events: InterAgentEventRecord[]): string | null {
  return events.length ? events[events.length - 1].event_id : null;
}

export function firstInterAgentEventId(events: InterAgentEventRecord[]): string | null {
  return events.length ? events[0].event_id : null;
}

export function eventDisplayLabel(event: InterAgentEventRecord): string {
  return event.event_type.replace(/^inter_agent\./, "").replace(/\./g, " ");
}

export function eventSummary(event: InterAgentEventRecord): string {
  for (const key of ["summary", "status", "reason", "message", "task", "label"]) {
    const value = event.payload[key];
    if (typeof value === "string" && value.trim()) {
      return value.trim();
    }
  }
  return event.visibility_plane;
}

export function runStatusLabel(status: string): string {
  if (status === "waiting_approval") {
    return "Waiting approval";
  }
  return status
    .split("_")
    .map((part) => part.slice(0, 1).toUpperCase() + part.slice(1))
    .join(" ");
}

export function isTerminalRunStatus(status: string): boolean {
  return status === "completed" || status === "failed" || status === "cancelled";
}

export function participantIcon(kind: string): string {
  if (kind === "orchestrator") {
    return "hub";
  }
  if (kind === "tool") {
    return "build";
  }
  if (kind === "human") {
    return "person_check";
  }
  if (kind === "system") {
    return "settings";
  }
  return "smart_toy";
}

export function defaultGraphSelection({
  approvals,
  artifacts,
  events,
  runDetail,
}: {
  approvals: InterAgentApprovalRecord[];
  artifacts: InterAgentArtifactRecord[];
  events: InterAgentEventRecord[];
  runDetail: InterAgentRunDetail | null;
}): InterAgentGraphSelection | null {
  const pendingApproval = approvals.find((approval) => approval.status === "pending");
  if (pendingApproval) {
    return { id: `approval:${pendingApproval.approval_id}`, kind: "approval", approvalId: pendingApproval.approval_id };
  }
  const lastEvent = events.at(-1);
  if (lastEvent) {
    return { id: `event:${lastEvent.event_id}`, kind: "event", eventId: lastEvent.event_id };
  }
  const lastArtifact = artifacts.at(-1);
  if (lastArtifact) {
    return { id: `artifact:${lastArtifact.artifact_id}`, kind: "artifact", artifactId: lastArtifact.artifact_id };
  }
  const orchestrator = runDetail?.participants.find((participant) => participant.kind === "orchestrator") || runDetail?.participants[0];
  if (orchestrator) {
    return { id: `participant:${orchestrator.participant_id}`, kind: "participant", participantId: orchestrator.participant_id };
  }
  return null;
}

export function selectionExists(selection: InterAgentGraphSelection | null, detail: InterAgentRunDetail | null, events: InterAgentEventRecord[], artifacts: InterAgentArtifactRecord[], approvals: InterAgentApprovalRecord[]): boolean {
  if (!selection) {
    return false;
  }
  if (selection.kind === "participant") {
    return Boolean(detail?.participants.some((participant) => participant.participant_id === selection.participantId));
  }
  if (selection.kind === "edge") {
    return Boolean(detail?.edges.some((edge) => edge.edge_id === selection.edgeId));
  }
  if (selection.kind === "event") {
    return events.some((event) => event.event_id === selection.eventId);
  }
  if (selection.kind === "artifact") {
    return artifacts.some((artifact) => artifact.artifact_id === selection.artifactId);
  }
  return approvals.some((approval) => approval.approval_id === selection.approvalId);
}

function interAgentEventSort(left: InterAgentEventRecord, right: InterAgentEventRecord): number {
  if (left.sequence !== right.sequence) {
    return left.sequence - right.sequence;
  }
  const timeOrder = String(left.created_at || "").localeCompare(String(right.created_at || ""));
  return timeOrder || left.event_id.localeCompare(right.event_id);
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}

function stringField(value: unknown): string {
  return typeof value === "string" ? value.trim() : "";
}
