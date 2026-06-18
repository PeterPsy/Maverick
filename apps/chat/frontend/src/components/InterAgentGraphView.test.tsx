/**
 * @vitest-environment happy-dom
 */
import { act } from "react";
import { createRoot } from "react-dom/client";
import type { Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { InterAgentRunDetail } from "../api/client";
import {
  getInterAgentRun,
  interruptInterAgentRun,
  listInterAgentRunApprovals,
  listInterAgentRunArtifacts,
  listInterAgentRunEvents,
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
});
