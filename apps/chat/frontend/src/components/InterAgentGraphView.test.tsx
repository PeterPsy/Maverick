/**
 * @vitest-environment happy-dom
 */
import { act } from "react";
import { createRoot } from "react-dom/client";
import type { Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type {
  InterAgentApprovalRecord,
  InterAgentParticipantTranscriptPayload,
  InterAgentRunDetail,
} from "../api/client";
import {
  closeInterAgentRun,
  getInterAgentParticipantTranscript,
  getInterAgentRun,
  interruptInterAgentRun,
  listInterAgentRunApprovals,
  listInterAgentRunArtifacts,
  listInterAgentRunEvents,
  resolveInterAgentApproval,
} from "../api/client";
import { InterAgentGraphView } from "./InterAgentGraphView";

vi.mock("../api/client", () => ({
  closeInterAgentRun: vi.fn(),
  getInterAgentParticipantTranscript: vi.fn(),
  getInterAgentRun: vi.fn(),
  interAgentWebSocketUrl: vi.fn(() => "ws://maverick.test/ws/inter-agent/runs/run-1"),
  interruptInterAgentRun: vi.fn(),
  listInterAgentRunApprovals: vi.fn(),
  listInterAgentRunArtifacts: vi.fn(),
  listInterAgentRunEvents: vi.fn(),
  resumeInterAgentRun: vi.fn(),
  resolveInterAgentApproval: vi.fn(),
}));

class FakeWebSocket {
  static OPEN = 1;
  static instances: FakeWebSocket[] = [];

  onclose: ((event: { code: number }) => void) | null = null;
  onerror: (() => void) | null = null;
  onmessage: ((event: { data: string }) => void) | null = null;
  onopen: (() => void) | null = null;
  readyState = FakeWebSocket.OPEN;
  sent: string[] = [];

  constructor() {
    FakeWebSocket.instances.push(this);
    window.setTimeout(() => this.onopen?.(), 0);
  }

  close() {
    this.readyState = 3;
    this.onclose?.({ code: 1000 });
  }

  send(payload: string) {
    this.sent.push(payload);
  }
}

let root: Root | null = null;
let container: HTMLDivElement | null = null;

function runDetail(overrides: Partial<InterAgentRunDetail> = {}): InterAgentRunDetail {
  const detail: InterAgentRunDetail = {
    run: {
      run_id: "run-1",
      workspace_id: "default",
      thread_id: "thread-1",
      root_runtime_session_id: "session-1",
      source_app_id: "chat",
      mode: "manager_tools",
      status: "running",
      created_by_user_id: "admin",
      orchestrator_participant_id: "orchestrator",
      budget_policy_id: "budget-1",
      budget_ledger_id: "ledger-1",
      visibility_level: "detail",
      created_at: "2026-06-18T10:00:00Z",
      updated_at: "2026-06-18T10:00:00Z",
      ended_at: null,
    },
    participants: [
      {
        participant_id: "orchestrator",
        workspace_id: "default",
        run_id: "run-1",
        kind: "orchestrator",
        execution_mode: "root_orchestrator",
        agent_type_id: null,
        label: "Orchestrator",
        runtime_session_id: null,
        status: "running",
        current_task_id: null,
        thread_visibility: "user",
        created_at: "2026-06-18T10:00:00Z",
        updated_at: "2026-06-18T10:00:00Z",
        sequence_index: 0,
      },
      {
        participant_id: "researcher",
        workspace_id: "default",
        run_id: "run-1",
        kind: "agent",
        execution_mode: "child_runtime_session",
        agent_type_id: "researcher",
        label: "Researcher",
        runtime_session_id: "child-1",
        status: "running",
        current_task_id: "task-1",
        thread_visibility: "hidden",
        created_at: "2026-06-18T10:00:00Z",
        updated_at: "2026-06-18T10:00:00Z",
        sequence_index: 1,
      },
    ],
    edges: [
      {
        edge_id: "edge-1",
        workspace_id: "default",
        run_id: "run-1",
        source_id: "orchestrator",
        target_id: "researcher",
        kind: "delegated",
        label: "Research",
        status: "active",
        created_at: "2026-06-18T10:00:01Z",
      },
    ],
    budget_policy: null,
    budget_ledger: null,
  };
  return { ...detail, ...overrides };
}

function transcriptPayload(participantId: string): InterAgentParticipantTranscriptPayload {
  const label = participantId === "researcher" ? "Researcher" : "Orchestrator";
  return {
    run_id: "run-1",
    participant: {
      participant_id: participantId,
      label,
      kind: participantId === "researcher" ? "agent" : "orchestrator",
      status: "running",
    },
    visibility_plane: "detail",
    items: [
      {
        message_id: `${participantId}:message:1`,
        kind: "input",
        role: "user",
        text: participantId === "researcher" ? "Find launch facts." : "Coordinate the run.",
        status: "completed",
        created_at: "2026-06-18T10:00:01Z",
      },
      {
        message_id: `${participantId}:message:2`,
        kind: "output",
        role: "participant",
        text: participantId === "researcher" ? "Research complete." : "Plan created.",
        status: "completed",
        created_at: "2026-06-18T10:00:02Z",
      },
    ],
    item_count: 2,
    truncated: false,
  };
}

function approvalRecord(overrides: Partial<InterAgentApprovalRecord> = {}): InterAgentApprovalRecord {
  return {
    approval_id: "approval-1",
    workspace_id: "default",
    run_id: "run-1",
    participant_id: "researcher",
    requested_by_participant_id: "orchestrator",
    operation_kind: "storage.write",
    resource_refs: [],
    summary: "Write a generated file.",
    risk_level: "medium",
    status: "pending",
    eligible_approver_user_ids: ["user:admin"],
    eligible_approver_roles: [],
    expires_at: "2026-06-18T10:30:00Z",
    ...overrides,
  };
}

async function settle() {
  await Promise.resolve();
  await Promise.resolve();
}

async function renderGraph(props: Partial<Parameters<typeof InterAgentGraphView>[0]> = {}) {
  container = document.createElement("div");
  document.body.append(container);
  root = createRoot(container);
  await act(async () => {
    root?.render(
      <InterAgentGraphView
        initialRunDetail={runDetail()}
        onClose={() => undefined}
        runId="run-1"
        {...props}
      />,
    );
    await settle();
  });
  return container;
}

beforeEach(() => {
  FakeWebSocket.instances = [];
  vi.stubGlobal("WebSocket", FakeWebSocket);
  vi.mocked(getInterAgentRun).mockResolvedValue(runDetail());
  vi.mocked(getInterAgentParticipantTranscript).mockImplementation(async (_runId, participantId) => transcriptPayload(participantId));
  vi.mocked(listInterAgentRunApprovals).mockResolvedValue({ items: [] });
  vi.mocked(listInterAgentRunArtifacts).mockResolvedValue({
    items: [],
    visibility_plane: "detail",
    limit: 240,
  });
  vi.mocked(listInterAgentRunEvents).mockResolvedValue({
    items: [],
    visibility_plane: "detail",
    limit: 240,
    has_more_before: false,
    has_more_after: false,
    oldest_event_id: null,
    newest_event_id: null,
  });
  vi.mocked(interruptInterAgentRun).mockResolvedValue({ run: { ...runDetail().run, status: "paused" } });
  vi.mocked(closeInterAgentRun).mockResolvedValue({
    run: { ...runDetail().run, status: "cancelled" },
    participant_cleanups: [],
  });
  vi.mocked(resolveInterAgentApproval).mockResolvedValue({ approval: approvalRecord({ status: "approved" }) });
});

afterEach(() => {
  root?.unmount();
  root = null;
  container?.remove();
  container = null;
  vi.clearAllMocks();
  vi.unstubAllGlobals();
});

describe("InterAgentGraphView", () => {
  it("renders loading and empty Agent nodes states", async () => {
    vi.mocked(getInterAgentRun).mockReturnValue(new Promise(() => undefined));
    const element = await renderGraph({ initialRunDetail: null });

    expect(element.textContent).toContain("Loading Agent nodes");

    await act(async () => {
      root?.render(<InterAgentGraphView initialRunDetail={runDetail({ participants: [], edges: [] })} onClose={() => undefined} runId="run-empty" />);
      await settle();
    });

    expect(element.textContent).toContain("No agent nodes yet.");
    expect(element.textContent).toContain("No participant selected.");
  });

  it("renders product-facing nodes and participant transcript without debug UI", async () => {
    const element = await renderGraph();

    expect(element.textContent).toContain("Agent nodes view");
    expect(element.textContent).toContain("2 nodes");
    expect(element.textContent).toContain("1 connections");
    expect(element.querySelectorAll("[data-participant-id]").length).toBe(2);
    expect(element.querySelector('[aria-label="Zoom out"]')).not.toBeNull();
    expect(element.querySelector('[aria-label="Fit graph"]')).not.toBeNull();
    expect(element.querySelector('[aria-label="Zoom in"]')).not.toBeNull();
    expect(element.textContent).toContain("Participant transcript");
    expect(element.textContent).toContain("Coordinate the run.");
    expect(element.textContent).toContain("Plan created.");
    expect(element.textContent).not.toContain("Event visibility");
    expect(element.textContent).not.toContain("Inspector");
    expect(element.textContent).not.toContain("Runtime session");
    expect(element.querySelector("pre")).toBeNull();
  });

  it("loads a safe transcript when an agent node is selected", async () => {
    const element = await renderGraph();
    const researcherNode = element.querySelector('[data-participant-id="researcher"]') as HTMLButtonElement | null;

    await act(async () => {
      researcherNode?.click();
      await settle();
    });

    expect(getInterAgentParticipantTranscript).toHaveBeenCalledWith("run-1", "researcher", { limit: 80 });
    expect(element.textContent).toContain("Find launch facts.");
    expect(element.textContent).toContain("Research complete.");
    expect(element.textContent).not.toContain("child-1");
  });

  it("keeps long labels visible inside the node map", async () => {
    const longLabel = "Researcher with a very long operational label that should wrap instead of overlapping adjacent node controls";
    const detail = runDetail({
      participants: [{ ...runDetail().participants[0], label: longLabel }],
      edges: [],
    });
    vi.mocked(getInterAgentRun).mockResolvedValue(detail);
    const element = await renderGraph({ initialRunDetail: detail });

    expect(element.textContent).toContain(longLabel);
    expect(element.querySelector(".chatapp-inter-agent-graph__node-copy")).not.toBeNull();
  });

  it("uses a navigable graph surface with separated node coordinates", async () => {
    const base = runDetail();
    const detail = runDetail({
      participants: [
        base.participants[0],
        base.participants[1],
        {
          ...base.participants[1],
          participant_id: "reviewer",
          agent_type_id: "reviewer",
          label: "Reviewer with a long label",
          runtime_session_id: "child-2",
          sequence_index: 2,
        },
        {
          ...base.participants[1],
          participant_id: "implementer",
          agent_type_id: "implementer",
          label: "Implementer with a long label",
          runtime_session_id: "child-3",
          sequence_index: 3,
        },
      ],
      edges: [
        base.edges[0],
        { ...base.edges[0], edge_id: "edge-2", target_id: "reviewer", label: "Review" },
        { ...base.edges[0], edge_id: "edge-3", target_id: "implementer", label: "Build" },
      ],
    });
    vi.mocked(getInterAgentRun).mockResolvedValue(detail);
    const element = await renderGraph({ initialRunDetail: detail });
    const surface = element.querySelector(".chatapp-inter-agent-graph__surface") as HTMLElement | null;
    const nodeStyles = Array.from(element.querySelectorAll<HTMLElement>("[data-participant-id]")).map((node) =>
      node.getAttribute("style") || "",
    );

    expect(surface?.getAttribute("style")).toContain("--graph-zoom");
    expect(nodeStyles.length).toBe(4);
    expect(new Set(nodeStyles).size).toBe(4);
    expect(nodeStyles.every((style) => style.includes("--graph-node-width: 220px"))).toBe(true);
  });

  it("sends pause and stop requests through the inter-agent API", async () => {
    const element = await renderGraph();

    await act(async () => {
      (Array.from(element.querySelectorAll("button")).find((button) => button.textContent?.includes("Pause")) as HTMLButtonElement | undefined)?.click();
      await settle();
    });
    await act(async () => {
      (Array.from(element.querySelectorAll("button")).find((button) => button.textContent?.includes("Stop")) as HTMLButtonElement | undefined)?.click();
      await settle();
    });

    expect(interruptInterAgentRun).toHaveBeenCalledWith("run-1", { reason: "chat_graph_pause" });
    expect(closeInterAgentRun).toHaveBeenCalledWith("run-1", { reason: "chat_graph_stop", terminal_status: "cancelled" });
  });

  it("resolves approval from the Agent nodes view", async () => {
    const pendingApproval = approvalRecord();
    const approvedApproval = approvalRecord({
      status: "approved",
      resolved_at: "2026-06-18T10:05:00Z",
      resolution_reason: "approved",
    });
    vi.mocked(resolveInterAgentApproval).mockResolvedValue({ approval: approvedApproval });
    vi.mocked(listInterAgentRunApprovals).mockResolvedValueOnce({ items: [pendingApproval] }).mockResolvedValue({ items: [] });
    const element = await renderGraph({ initialApprovals: [pendingApproval] });

    expect(element.textContent).toContain("pending approvals");

    await act(async () => {
      (Array.from(element.querySelectorAll("button")).find((button) => button.textContent === "Approve") as HTMLButtonElement | undefined)?.click();
      await settle();
    });

    expect(resolveInterAgentApproval).toHaveBeenCalledWith("approval-1", { approved: true });
  });

  it("applies participant.started live events to visible node state", async () => {
    const base = runDetail();
    const createdDetail = runDetail({
      run: { ...base.run, status: "created" },
      participants: base.participants.map((participant) =>
        participant.participant_id === "researcher"
          ? { ...participant, runtime_session_id: null, status: "idle" }
          : participant,
      ),
    });
    vi.mocked(getInterAgentRun).mockResolvedValue(createdDetail);
    const element = await renderGraph({ initialRunDetail: createdDetail });

    expect(element.textContent).toContain("agent - idle");

    await act(async () => {
      FakeWebSocket.instances[0]?.onmessage?.({
        data: JSON.stringify({
          type: "inter_agent.event",
          event: {
            event_id: "event-started",
            workspace_id: "default",
            run_id: "run-1",
            thread_id: "thread-1",
            root_runtime_session_id: "session-1",
            participant_id: "researcher",
            runtime_session_id: "child-99",
            runtime_turn_id: null,
            runtime_event_id: null,
            event_type: "inter_agent.participant.started",
            visibility_plane: "detail",
            sequence: 2,
            correlation_id: "child-99",
            idempotency_key: "event-started",
            payload: { participant_id: "researcher", runtime_session_id: "child-99" },
            created_at: "2026-06-18T10:02:00Z",
          },
        }),
      });
      await settle();
    });

    expect(element.textContent).toContain("Running");
    expect(element.textContent).toContain("agent - running");
  });
});
