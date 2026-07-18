/**
 * @vitest-environment happy-dom
 */
import { act } from "react";
import { createRoot } from "react-dom/client";
import type { Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type {
  ChatMessage,
  InterAgentApprovalRecord,
  InterAgentEventRecord,
  InterAgentParticipantTranscriptPayload,
  InterAgentRunDetail,
} from "../api/client";
import {
  getInterAgentParticipantTranscript,
  getInterAgentRun,
  listInterAgentRunApprovals,
  listInterAgentRunArtifacts,
  listInterAgentRunEvents,
  resolveInterAgentApproval,
} from "../api/client";
import { InterAgentGraphView, graphBoardLayout, graphFlowEdges } from "./InterAgentGraphView";

vi.mock("../api/client", () => ({
  getInterAgentParticipantTranscript: vi.fn(),
  getInterAgentRun: vi.fn(),
  interAgentWebSocketUrl: vi.fn(() => "ws://maverick.test/ws/inter-agent/runs/run-1"),
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

class FakeResizeObserver {
  disconnect() {}
  observe() {}
  unobserve() {}
}

let root: Root | null = null;
let container: HTMLDivElement | null = null;
let getBoundingClientRectSpy: ReturnType<typeof vi.spyOn> | null = null;

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

function projectedResearcherMessages(): ChatMessage[] {
  return [
    {
      id: "researcher:agent:1",
      role: "agent",
      content: "Checking the primary sources.",
      createdAt: "2026-06-18T10:01:00Z",
      status: "complete",
      sourceLabel: "Researcher",
      sourceParticipantId: "researcher",
      sourceRunId: "run-1",
    },
    {
      id: "researcher:tool:1",
      role: "tool",
      content: "Tool Used",
      createdAt: "2026-06-18T10:01:01Z",
      status: "complete",
      sourceLabel: "Researcher",
      sourceParticipantId: "researcher",
      sourceRunId: "run-1",
      toolCall: {
        id: "web-search-1",
        name: "web_search",
        status: "started",
        detail: { tool_kind: "web_search", query: "Maverick launch" },
        createdAt: "2026-06-18T10:01:01Z",
      },
    },
  ];
}

function artifactEvent(overrides: Partial<InterAgentEventRecord> = {}): InterAgentEventRecord {
  return {
    event_id: "event-artifact-1",
    workspace_id: "default",
    run_id: "run-1",
    thread_id: "thread-1",
    root_runtime_session_id: "session-1",
    participant_id: "researcher",
    runtime_session_id: "child-1",
    runtime_turn_id: null,
    runtime_event_id: null,
    event_type: "inter_agent.artifact.created",
    visibility_plane: "detail",
    sequence: 3,
    correlation_id: "artifact-1",
    idempotency_key: "artifact-1",
    payload: {
      artifact_refs: [
        {
          label: "Research report",
          workspace_relative_path: "storage/generated/reports/research.md",
        },
      ],
      partial_output: "Draft report summary.",
      status: "partial",
    },
    created_at: "2026-06-18T10:03:00Z",
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
  getBoundingClientRectSpy = vi.spyOn(HTMLElement.prototype, "getBoundingClientRect").mockImplementation(function (this: HTMLElement) {
    const element = this;
    if (element.classList.contains("chatapp-inter-agent-graph__board")) {
      return {
        bottom: 420,
        height: 420,
        left: 0,
        right: 760,
        top: 0,
        width: 760,
        x: 0,
        y: 0,
        toJSON: () => undefined,
      };
    }
    return {
      bottom: 72,
      height: 72,
      left: 0,
      right: 220,
      top: 0,
      width: 220,
      x: 0,
      y: 0,
      toJSON: () => undefined,
    };
  });
  vi.stubGlobal("ResizeObserver", FakeResizeObserver);
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
  vi.mocked(resolveInterAgentApproval).mockResolvedValue({ approval: approvalRecord({ status: "approved" }) });
});

afterEach(() => {
  root?.unmount();
  root = null;
  container?.remove();
  container = null;
  getBoundingClientRectSpy?.mockRestore();
  getBoundingClientRectSpy = null;
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
    expect(element.querySelector(".chatapp-inter-agent-graph__transcript")).toBeNull();
  });

  it("renders full-screen nodes without graph chrome or debug UI", async () => {
    const element = await renderGraph();

    expect(element.querySelector('[aria-label="Back to chat"]')).not.toBeNull();
    expect(element.querySelectorAll("[data-participant-id]").length).toBe(2);
    expect(element.querySelector('[aria-label="Zoom out"]')).toBeNull();
    expect(element.querySelector('[aria-label="Fit graph"]')).toBeNull();
    expect(element.querySelector('[aria-label="Zoom in"]')).toBeNull();
    expect(element.querySelector(".chatapp-inter-agent-graph__body")?.classList.contains("has-transcript")).toBe(false);
    expect(element.textContent).not.toContain("Agent nodes view");
    expect(element.textContent).not.toContain("2 nodes");
    expect(element.textContent).not.toContain("1 connections");
    expect(element.textContent).not.toContain("Coordinate the run.");
    expect(element.textContent).not.toContain("Event visibility");
    expect(element.textContent).not.toContain("Inspector");
    expect(element.textContent).not.toContain("Runtime session");
    expect(element.querySelector("pre")).toBeNull();
  });

  it("shows the shared working border and a bounded static latest activity inside agent nodes", async () => {
    const element = await renderGraph({ messages: projectedResearcherMessages() });
    const researcherNodeButton = element.querySelector('[data-participant-id="researcher"]') as HTMLButtonElement | null;
    const researcherNode = researcherNodeButton?.closest(".chatapp-inter-agent-graph__node");

    expect(researcherNode?.classList.contains("is-working")).toBe(true);
    expect(researcherNode?.querySelector(".chatapp-live-border-glow")).not.toBeNull();
    expect(researcherNode?.querySelector(".chatapp-inter-agent-graph__node-activity")?.textContent).toContain("Tool in progress");
    expect(researcherNode?.querySelector(".chatapp-inter-agent-graph__node-activity")?.textContent).toContain("Web search");
    expect(researcherNode?.querySelector(".chatapp-inter-agent-graph__node-activity-heading")).not.toBeNull();
    expect(researcherNode?.querySelector('[aria-label*="latest activity"]')).toBeNull();
    expect(researcherNode?.querySelector(".chatapp-inter-agent-graph__node-activity-caret")).toBeNull();
  });

  it("loads a safe transcript when an agent node is selected", async () => {
    const element = await renderGraph();
    const researcherNode = element.querySelector('[data-participant-id="researcher"]') as HTMLButtonElement | null;

    await act(async () => {
      researcherNode?.click();
      await settle();
    });

    expect(getInterAgentParticipantTranscript).toHaveBeenCalledWith("run-1", "researcher", { limit: 80 });
    expect(element.querySelector('[aria-label="Researcher transcript"]')).not.toBeNull();
    expect(element.querySelector(".chatapp-inter-agent-graph__body")?.classList.contains("has-transcript")).toBe(true);
    expect(element.querySelector(".chatapp-inter-agent-graph__input-summary")?.textContent).toContain("Find launch facts.");
    expect(element.querySelector(".chatapp-inter-agent-graph__transcript-title summary")).not.toBeNull();
    expect(element.querySelector(".chatapp-inter-agent-graph__transcript-list .chatapp-agent-block")).not.toBeNull();
    const outputText = element.querySelector(".chatapp-inter-agent-graph__transcript-list")?.textContent || "";
    expect(outputText).toContain("Research complete.");
    expect(outputText).not.toContain("Find launch facts.");
    expect(element.textContent).not.toContain("child-1");
  });

  it("keeps the complete input summary available for the scrollable participant header", async () => {
    const longInput = `Review the complete request. ${"Keep this operational detail visible. ".repeat(14)}Final input marker.`;
    vi.mocked(getInterAgentParticipantTranscript).mockResolvedValue({
      ...transcriptPayload("researcher"),
      items: [
        {
          ...transcriptPayload("researcher").items[0],
          text: longInput,
        },
      ],
      item_count: 1,
    });
    const element = await renderGraph();

    await act(async () => {
      (element.querySelector('[data-participant-id="researcher"]') as HTMLButtonElement | null)?.click();
      await settle();
    });

    const summary = element.querySelector(".chatapp-inter-agent-graph__input-summary p");
    expect(summary?.textContent).toBe(longInput);
    expect(summary?.textContent).toContain("Final input marker.");
  });

  it("renders projected participant text and tools with the normal chat blocks", async () => {
    const element = await renderGraph({ messages: projectedResearcherMessages() });

    await act(async () => {
      (element.querySelector('[data-participant-id="researcher"]') as HTMLButtonElement | null)?.click();
      await settle();
    });

    const transcript = element.querySelector('[aria-label="Researcher transcript"]');
    expect(transcript?.textContent).toContain("Checking the primary sources.");
    expect(transcript?.textContent).toContain("Tool Used");
    expect(transcript?.textContent).toContain("Web search");
    expect(transcript?.querySelectorAll(".chatapp-bubble").length).toBe(2);
    expect(transcript?.querySelector(".chatapp-tool-inline__row")).not.toBeNull();
    expect(transcript?.querySelector(".chatapp-agent-block")).not.toBeNull();
  });

  it("keeps projected participant activity scoped to the selected run and participant", async () => {
    const messages: ChatMessage[] = [
      ...projectedResearcherMessages(),
      {
        id: "orchestrator:agent:private",
        role: "agent",
        content: "Orchestrator-only update.",
        createdAt: "2026-06-18T10:01:02Z",
        status: "complete",
        sourceLabel: "Orchestrator",
        sourceParticipantId: "orchestrator",
        sourceRunId: "run-1",
      },
      {
        id: "researcher:agent:other-run",
        role: "agent",
        content: "Different-run researcher update.",
        createdAt: "2026-06-18T10:01:03Z",
        status: "complete",
        sourceLabel: "Researcher",
        sourceParticipantId: "researcher",
        sourceRunId: "run-2",
      },
    ];
    const element = await renderGraph({ messages });

    await act(async () => {
      (element.querySelector('[data-participant-id="researcher"]') as HTMLButtonElement | null)?.click();
      await settle();
    });

    const transcriptText = element.querySelector('[aria-label="Researcher transcript"]')?.textContent || "";
    expect(transcriptText).toContain("Checking the primary sources.");
    expect(transcriptText).not.toContain("Orchestrator-only update.");
    expect(transcriptText).not.toContain("Different-run researcher update.");
  });

  it("renders participant artifacts as product-facing records with Storage links", async () => {
    const element = await renderGraph({ initialEvents: [artifactEvent()] });
    const researcherNode = element.querySelector('[data-participant-id="researcher"]') as HTMLButtonElement | null;

    await act(async () => {
      researcherNode?.click();
      await settle();
    });

    const artifactLink = element.querySelector(".chatapp-inter-agent-graph__artifact-list a") as HTMLAnchorElement | null;
    expect(element.textContent).toContain("Artifacts");
    expect(element.textContent).toContain("Research report");
    expect(element.textContent).toContain("Partial - storage/generated/reports/research.md");
    expect(element.textContent).toContain("Draft report summary.");
    expect(artifactLink?.getAttribute("href")).toBe(
      "/app/storage?workspace_relative_path=storage%2Fgenerated%2Freports%2Fresearch.md",
    );
  });

  it("renders unsafe artifact deep links as text instead of anchors", async () => {
    const element = await renderGraph({
      initialEvents: [
        artifactEvent({
          payload: {
            artifact_refs: [
              {
                label: "Unsafe report",
                deep_link: "javascript:alert(1)",
              },
            ],
            status: "created",
          },
        }),
      ],
    });
    const researcherNode = element.querySelector('[data-participant-id="researcher"]') as HTMLButtonElement | null;

    await act(async () => {
      researcherNode?.click();
      await settle();
    });

    expect(element.textContent).toContain("Unsafe report");
    expect(element.querySelector(".chatapp-inter-agent-graph__artifact-list a")).toBeNull();
    expect(element.innerHTML).not.toContain("javascript:");
  });

  it("shows run-level artifacts on the orchestrator transcript fallback", async () => {
    const element = await renderGraph({
      initialEvents: [
        artifactEvent({
          participant_id: null,
          payload: {
            artifact_refs: [
              {
                label: "Run artifact",
                workspace_relative_path: "storage/generated/reports/run-summary.md",
              },
            ],
            status: "created",
          },
        }),
      ],
    });

    await act(async () => {
      await settle();
    });

    const orchestratorNode = element.querySelector('[data-participant-id="orchestrator"]') as HTMLButtonElement | null;
    await act(async () => {
      orchestratorNode?.click();
      await settle();
    });

    const artifactLink = element.querySelector(".chatapp-inter-agent-graph__artifact-list a") as HTMLAnchorElement | null;
    expect(element.textContent).toContain("Run artifact");
    expect(artifactLink?.getAttribute("href")).toBe(
      "/app/storage?workspace_relative_path=storage%2Fgenerated%2Freports%2Frun-summary.md",
    );
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

  it("uses a navigable React Flow surface with selectable nodes", async () => {
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
    const board = element.querySelector('[data-react-flow-agent-graph="true"]') as HTMLElement | null;
    const flow = element.querySelector(".react-flow") as HTMLElement | null;
    const nodeIds = Array.from(element.querySelectorAll<HTMLElement>("[data-participant-id]")).map((node) =>
      node.getAttribute("data-participant-id") || "",
    );

    expect(board?.getAttribute("style") || "").not.toContain("--graph-board-min-height");
    expect(flow).not.toBeNull();
    expect(nodeIds.length).toBe(4);
    expect(new Set(nodeIds).size).toBe(4);
    expect(element.querySelector(".react-flow__viewport")).not.toBeNull();

    await act(async () => {
      (element.querySelector('[data-participant-id="reviewer"]') as HTMLButtonElement | null)?.click();
      await settle();
    });

    expect(element.querySelector('[aria-label="Reviewer with a long label transcript"]')).not.toBeNull();
    expect(element.textContent).toContain("Reviewer with a long label");
  });

  it("routes return connections through side handles to avoid crossing the board", async () => {
    const base = runDetail();
    const implementer = {
      ...base.participants[1],
      participant_id: "implementer",
      agent_type_id: "implementer",
      label: "Implementer",
      runtime_session_id: "child-implementer",
      status: "completed",
      sequence_index: 1,
    };
    const reviewer = {
      ...base.participants[1],
      participant_id: "reviewer",
      agent_type_id: "reviewer",
      label: "Reviewer",
      runtime_session_id: "child-reviewer",
      status: "completed",
      sequence_index: 2,
    };
    const detail = runDetail({
      participants: [base.participants[0], implementer, reviewer],
      edges: [
        {
          ...base.edges[0],
          edge_id: "edge-implementation",
          source_id: "orchestrator",
          target_id: "implementer",
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
    const element = await renderGraph({ initialRunDetail: detail });
    const layout = graphBoardLayout(detail.participants, detail.edges, detail.run.orchestrator_participant_id);
    const flowEdges = graphFlowEdges(detail.edges, layout.nodesById);
    const implementationEdge = flowEdges.find((edge) => edge.id === "edge-implementation");
    const reviewEdge = flowEdges.find((edge) => edge.id === "edge-review");
    const finalReviewEdge = flowEdges.find((edge) => edge.id === "edge-final-review");

    expect(element.querySelectorAll(".chatapp-inter-agent-graph__handle").length).toBe(24);
    expect(element.querySelectorAll(".chatapp-inter-agent-graph__handle.is-right").length).toBe(6);
    expect(layout.nodesById.get("reviewer")?.depth).toBe(2);
    expect(implementationEdge?.sourceHandle).toBe("source-bottom");
    expect(implementationEdge?.targetHandle).toBe("target-top");
    expect(reviewEdge?.sourceHandle).toBe("source-bottom");
    expect(reviewEdge?.targetHandle).toBe("target-top");
    expect(finalReviewEdge?.className).toContain("is-return");
    expect(finalReviewEdge?.label).toBe("Final review");
    expect(finalReviewEdge?.pathOptions?.offset).toBeGreaterThanOrEqual(96);
    expect(finalReviewEdge?.sourceHandle).toBe("source-right");
    expect(finalReviewEdge?.targetHandle).toBe("target-right");

    const analyst = { ...implementer, participant_id: "analyst", label: "Analyst", sequence_index: 1 };
    const synthesizer = { ...implementer, participant_id: "synthesizer", label: "Synthesizer", sequence_index: 3 };
    const groupDetail = runDetail({
      participants: [base.participants[0], analyst, reviewer, synthesizer],
      edges: [
        {
          ...base.edges[0],
          edge_id: "edge-analysis",
          source_id: "orchestrator",
          target_id: "analyst",
        },
        {
          ...base.edges[0],
          edge_id: "edge-reviewer",
          source_id: "orchestrator",
          target_id: "reviewer",
        },
        {
          ...base.edges[0],
          edge_id: "edge-analyst-synth",
          source_id: "analyst",
          target_id: "synthesizer",
          kind: "depends_on",
        },
        {
          ...base.edges[0],
          edge_id: "edge-reviewer-synth",
          source_id: "reviewer",
          target_id: "synthesizer",
          kind: "depends_on",
        },
        {
          ...base.edges[0],
          edge_id: "edge-synth-final",
          source_id: "synthesizer",
          target_id: "orchestrator",
          kind: "produced",
        },
      ],
    });
    const groupLayout = graphBoardLayout(
      groupDetail.participants,
      groupDetail.edges,
      groupDetail.run.orchestrator_participant_id,
    );
    const groupReturnEdge = graphFlowEdges(groupDetail.edges, groupLayout.nodesById).find((edge) => edge.id === "edge-synth-final");

    expect(groupReturnEdge?.className).toContain("is-return");
    expect(groupReturnEdge?.pathOptions?.offset).toBeGreaterThan(200);
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

    expect(element.textContent).toContain("Write a generated file.");

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

    expect(element.textContent).toContain("agent - running");
  });
});
