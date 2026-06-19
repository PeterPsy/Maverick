/**
 * @vitest-environment happy-dom
 */
import { act } from "react";
import { createRoot } from "react-dom/client";
import type { Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { InterAgentApprovalRecord, InterAgentRunDetail } from "../api/client";
import {
  closeInterAgentRun,
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
    await Promise.resolve();
  });
  return container;
}

beforeEach(() => {
  FakeWebSocket.instances = [];
  vi.stubGlobal("WebSocket", FakeWebSocket);
  vi.mocked(getInterAgentRun).mockResolvedValue(runDetail());
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
  it("renders loading and empty graph states", async () => {
    vi.mocked(getInterAgentRun).mockReturnValue(new Promise(() => undefined));
    const element = await renderGraph({ initialRunDetail: null });

    expect(element.textContent).toContain("Loading graph");

    await act(async () => {
      root?.render(<InterAgentGraphView initialRunDetail={runDetail({ participants: [], edges: [] })} onClose={() => undefined} runId="run-empty" />);
      await Promise.resolve();
    });

    expect(element.textContent).toContain("No participants yet.");
    expect(element.textContent).toContain("No events for this filter.");
    expect(element.textContent).toContain("No artifacts recorded.");
  });

  it("renders graph edges as visual board connectors", async () => {
    const element = await renderGraph();
    const edgePath = element.querySelector('.chatapp-inter-agent-graph__edge-path[data-edge-id="edge-1"]');
    const edgeChip = element.querySelector(".chatapp-inter-agent-graph__edge-chip") as HTMLButtonElement | null;

    expect(edgePath).not.toBeNull();
    expect(edgeChip?.textContent).toContain("Research");
    expect(element.textContent).not.toContain("No graph links recorded.");

    await act(async () => {
      edgeChip?.click();
      await Promise.resolve();
    });

    expect(edgePath?.getAttribute("class")).toContain("is-selected");
    expect(element.textContent).toContain("Source");
    expect(element.textContent).toContain("orchestrator");
    expect(element.textContent).toContain("Target");
    expect(element.textContent).toContain("researcher");
  });

  it("renders a multi-worker demo graph with timeline, artifacts, and stop control", async () => {
    const base = runDetail();
    const detail = runDetail({
      run: { ...base.run, mode: "sequential" },
      participants: [
        base.participants[0],
        {
          ...base.participants[1],
          participant_id: "implementer",
          label: "Implementer",
          runtime_session_id: "child-implementer",
          status: "completed",
        },
        {
          ...base.participants[1],
          participant_id: "reviewer",
          label: "Reviewer",
          runtime_session_id: "child-reviewer",
          status: "running",
        },
      ],
      edges: [
        {
          ...base.edges[0],
          edge_id: "edge-implementation",
          source_id: "orchestrator",
          target_id: "implementer",
          kind: "delegated",
          label: "Implementation",
        },
        {
          ...base.edges[0],
          edge_id: "edge-review",
          source_id: "implementer",
          target_id: "reviewer",
          kind: "reviewed_by",
          label: "Review",
        },
        {
          ...base.edges[0],
          edge_id: "edge-final-review",
          source_id: "reviewer",
          target_id: "orchestrator",
          kind: "produced",
          label: "Final review",
        },
      ],
    });
    vi.mocked(getInterAgentRun).mockResolvedValue(detail);
    const element = await renderGraph({
      initialRunDetail: detail,
      initialEvents: [
        {
          event_id: "event-plan",
          workspace_id: "default",
          run_id: "run-1",
          thread_id: "thread-1",
          root_runtime_session_id: "session-1",
          participant_id: "orchestrator",
          runtime_session_id: null,
          runtime_turn_id: null,
          runtime_event_id: null,
          event_type: "inter_agent.plan.summary_created",
          visibility_plane: "summary",
          sequence: 1,
          correlation_id: "event-plan",
          idempotency_key: "event-plan",
          payload: { summary: "Orchestrator started a staged multi-agent run with 2 worker nodes." },
          created_at: "2026-06-18T10:00:01Z",
        },
        {
          event_id: "event-artifact",
          workspace_id: "default",
          run_id: "run-1",
          thread_id: "thread-1",
          root_runtime_session_id: "session-1",
          participant_id: "reviewer",
          runtime_session_id: "child-reviewer",
          runtime_turn_id: "turn-reviewer",
          runtime_event_id: null,
          event_type: "inter_agent.artifact.created",
          visibility_plane: "detail",
          sequence: 2,
          correlation_id: "event-artifact",
          idempotency_key: "event-artifact",
          payload: {
            artifact_refs: [{ artifact_id: "artifact-final", label: "Final brief", workspace_relative_path: "storage/generated/final.md" }],
            partial_output: "Reviewer draft before final synthesis.",
            status: "created",
          },
          created_at: "2026-06-18T10:00:02Z",
        },
      ],
    });

    expect(element.textContent).toContain("3 nodes");
    expect(element.querySelectorAll("[data-participant-id]").length).toBe(3);
    expect(element.textContent).toContain("Implementer");
    expect(element.textContent).toContain("Reviewer");
    expect(element.querySelectorAll(".chatapp-inter-agent-graph__edge-path").length).toBe(3);
    expect(element.textContent).toContain("Orchestrator started a staged multi-agent run with 2 worker nodes.");
    expect(element.textContent).toContain("Final brief");

    const reviewEdge = Array.from(element.querySelectorAll(".chatapp-inter-agent-graph__edge-chip")).find((button) =>
      button.textContent?.includes("Review"),
    ) as HTMLButtonElement | undefined;
    await act(async () => {
      reviewEdge?.click();
      await Promise.resolve();
    });
    expect(element.textContent).toContain("Source");
    expect(element.textContent).toContain("implementer");
    expect(element.textContent).toContain("Target");
    expect(element.textContent).toContain("reviewer");

    const artifactButton = Array.from(element.querySelectorAll(".chatapp-inter-agent-graph__artifact-list button")).find((button) =>
      button.textContent?.includes("Final brief"),
    ) as HTMLButtonElement | undefined;
    await act(async () => {
      artifactButton?.click();
      await Promise.resolve();
    });
    expect(element.textContent).toContain("storage/generated/final.md");
    expect(element.textContent).toContain("Reviewer draft before final synthesis.");

    await act(async () => {
      (Array.from(element.querySelectorAll("button")).find((button) => button.textContent?.includes("Stop")) as HTMLButtonElement | undefined)?.click();
      await Promise.resolve();
      await Promise.resolve();
    });
    expect(closeInterAgentRun).toHaveBeenCalledWith("run-1", { reason: "chat_graph_stop", terminal_status: "cancelled" });
  });

  it("keeps long labels visible inside graph panels", async () => {
    const longLabel = "Researcher with a very long operational label that should wrap instead of overlapping adjacent graph controls";
    const longSummary = "A very long event summary that should remain inspectable without hiding the timeline row content";
    const detail = runDetail({
      participants: [{ ...runDetail().participants[0], label: longLabel }],
    });
    vi.mocked(getInterAgentRun).mockResolvedValue(detail);
    const element = await renderGraph({
      initialRunDetail: detail,
      initialEvents: [
        {
          event_id: "event-1",
          workspace_id: "default",
          run_id: "run-1",
          thread_id: "thread-1",
          root_runtime_session_id: "session-1",
          participant_id: "orchestrator",
          runtime_session_id: null,
          runtime_turn_id: null,
          runtime_event_id: null,
          event_type: "inter_agent.summary.updated",
          visibility_plane: "detail",
          sequence: 1,
          correlation_id: "event-1",
          idempotency_key: "event-1",
          payload: { summary: longSummary },
          created_at: "2026-06-18T10:01:00Z",
        },
      ],
    });

    expect(element.textContent).toContain(longLabel);
    expect(element.textContent).toContain(longSummary);
    expect(element.querySelector(".chatapp-inter-agent-graph__node-copy")).not.toBeNull();
  });

  it("clears detail-only events when switching to the summary filter", async () => {
    const detailOnlySummary = "Detail-only task update";
    const element = await renderGraph({
      initialEvents: [
        {
          event_id: "event-detail-1",
          workspace_id: "default",
          run_id: "run-1",
          thread_id: "thread-1",
          root_runtime_session_id: "session-1",
          participant_id: "orchestrator",
          runtime_session_id: null,
          runtime_turn_id: null,
          runtime_event_id: null,
          event_type: "inter_agent.task.assigned",
          visibility_plane: "detail",
          sequence: 1,
          correlation_id: "event-detail-1",
          idempotency_key: "event-detail-1",
          payload: { summary: detailOnlySummary },
          created_at: "2026-06-18T10:01:00Z",
        },
      ],
    });

    expect(element.textContent).toContain(detailOnlySummary);

    await act(async () => {
      (Array.from(element.querySelectorAll(".chatapp-inter-agent-graph__segments button")).find(
        (button) => button.textContent === "summary",
      ) as HTMLButtonElement | undefined)?.click();
      await Promise.resolve();
      await Promise.resolve();
    });

    expect(element.textContent).not.toContain(detailOnlySummary);
    expect(element.textContent).toContain("No events for this filter.");
    expect(listInterAgentRunEvents).toHaveBeenCalledWith("run-1", { visibilityPlane: "summary", limit: 240 });
  });

  it("sends pause requests through the inter-agent API", async () => {
    const element = await renderGraph();

    await act(async () => {
      (Array.from(element.querySelectorAll("button")).find((button) => button.textContent?.includes("Pause")) as HTMLButtonElement | undefined)?.click();
      await Promise.resolve();
    });

    expect(interruptInterAgentRun).toHaveBeenCalledWith("run-1", { reason: "chat_graph_pause" });
  });

  it("resolves approval from the graph inspector and updates local approval state", async () => {
    const pendingApproval = approvalRecord();
    const approvedApproval = approvalRecord({
      status: "approved",
      resolved_at: "2026-06-18T10:05:00Z",
      resolution_reason: "approved",
    });
    vi.mocked(resolveInterAgentApproval).mockResolvedValue({ approval: approvedApproval });
    vi.mocked(listInterAgentRunApprovals).mockResolvedValueOnce({ items: [pendingApproval] }).mockResolvedValue({ items: [approvedApproval] });
    const element = await renderGraph({ initialApprovals: [pendingApproval] });

    expect(element.textContent).toContain("pending");

    await act(async () => {
      (Array.from(element.querySelectorAll("button")).find((button) => button.textContent === "Approve") as HTMLButtonElement | undefined)?.click();
      await Promise.resolve();
      await Promise.resolve();
    });

    expect(resolveInterAgentApproval).toHaveBeenCalledWith("approval-1", { approved: true });
    expect(element.textContent).toContain("approved");
    expect(Array.from(element.querySelectorAll("button")).some((button) => button.textContent === "Approve")).toBe(false);
  });

  it("applies participant.started live events to graph run detail", async () => {
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
      await Promise.resolve();
    });

    expect(element.textContent).toContain("Running");
    expect(element.textContent).toContain("agent - running");
  });
});
