import { beforeEach, describe, expect, it } from "vitest";
import type { RuntimeEvent } from "../api/client";
import { clearTranscriptProjectionCache, eventsToMessages } from "./transcript";

function event(overrides: Partial<RuntimeEvent>): RuntimeEvent {
  return {
    event_id: "event-1",
    session_id: "session-1",
    turn_id: "turn-1",
    event_type: "runtime.turn.queued",
    payload: {},
    created_at: "2026-04-19T00:00:00.000Z",
    ...overrides,
  };
}

describe("runtime event transcript projection", () => {
  beforeEach(() => {
    clearTranscriptProjectionCache();
  });

  it("reuses projections for equivalent event lists with the same last event", () => {
    const firstEvents = [
      event({
        event_id: "queued-cache",
        event_type: "runtime.turn.queued",
        payload: { input_text: "hello", client_message_id: "client-message-cache" },
      }),
    ];
    const secondEvents = firstEvents.map((item) => ({ ...item }));

    const firstProjection = eventsToMessages(firstEvents);
    const secondProjection = eventsToMessages(secondEvents);

    expect(secondProjection).toBe(firstProjection);
  });

  it("projects one human message from a queued runtime turn", () => {
    const messages = eventsToMessages([
      event({
        event_type: "runtime.turn.queued",
        payload: { input_text: "hello", client_message_id: "client-message-1" },
      }),
    ]);
    expect(messages).toMatchObject([{ id: "client-message-1", role: "human", content: "hello", status: "complete" }]);
  });

  it("projects steered messages inside the active turn without merging assistant segments", () => {
    const messages = eventsToMessages([
      event({
        event_id: "queued-1",
        event_type: "runtime.turn.queued",
        payload: { input_text: "start", client_message_id: "client-message-1" },
      }),
      event({
        event_id: "delta-before-steer",
        event_type: "runtime.output.delta",
        payload: { text: "Working on the first request." },
      }),
      event({
        event_id: "steered-1",
        event_type: "runtime.message.steered",
        payload: { input_text: "also verify the tests", client_message_id: "client-message-2" },
      }),
      event({
        event_id: "delta-after-steer",
        event_type: "runtime.output.delta",
        payload: { text: "Now including the tests." },
      }),
    ]);

    expect(messages.map(({ id, role, content }) => ({ id, role, content }))).toEqual([
      { id: "client-message-1", role: "human", content: "start" },
      { id: "turn-1:agent:stream:0", role: "agent", content: "Working on the first request." },
      { id: "client-message-2", role: "human", content: "also verify the tests" },
      { id: "turn-1:agent:stream:1", role: "agent", content: "Now including the tests." },
    ]);
  });

  it("keeps steered-message ordering when the provider also emits complete final text", () => {
    const messages = eventsToMessages([
      event({
        event_id: "queued-final-order",
        event_type: "runtime.turn.queued",
        payload: { input_text: "start", client_message_id: "client-final-order-1" },
      }),
      event({
        event_id: "delta-final-order-before",
        event_type: "runtime.output.delta",
        payload: { text: "First segment. " },
      }),
      event({
        event_id: "steered-final-order",
        event_type: "runtime.message.steered",
        payload: { input_text: "add tests", client_message_id: "client-final-order-2" },
      }),
      event({
        event_id: "delta-final-order-after",
        event_type: "runtime.output.delta",
        payload: { text: "Second segment." },
      }),
      event({
        event_id: "final-final-order",
        event_type: "runtime.output.final",
        payload: { complete_text: "First segment. Second segment." },
      }),
    ]);

    expect(messages.map(({ role, content }) => ({ role, content }))).toEqual([
      { role: "human", content: "start" },
      { role: "agent", content: "First segment. " },
      { role: "human", content: "add tests" },
      { role: "agent", content: "Second segment." },
    ]);
  });

  it("projects attachment-only steered messages", () => {
    const messages = eventsToMessages([
      event({
        event_id: "steered-attachment",
        event_type: "runtime.message.steered",
        payload: {
          client_message_id: "client-attachment",
          attachments: [{ id: "file-1", name: "report.pdf", workspace_relative_path: "storage/uploaded/report.pdf" }],
        },
      }),
    ]);

    expect(messages).toMatchObject([
      { id: "client-attachment", role: "human", content: "", attachments: [{ id: "file-1", name: "report.pdf" }] },
    ]);
  });

  it("deduplicates a retried steered message by client message id", () => {
    const messages = eventsToMessages([
      event({
        event_id: "steered-1",
        event_type: "runtime.message.steered",
        payload: { input_text: "one direction", client_message_id: "client-message-steer" },
      }),
      event({
        event_id: "steered-duplicate",
        event_type: "runtime.message.steered",
        payload: { input_text: "one direction", client_message_id: "client-message-steer" },
      }),
    ]);

    expect(messages.filter((message) => message.role === "human")).toHaveLength(1);
  });

  it("preserves structured app references on human messages", () => {
    const messages = eventsToMessages([
      event({
        event_type: "runtime.turn.queued",
        payload: {
          input_text: "controlla @Chat",
          app_references: [{ type: "app", app_id: "chat", label: "Chat" }],
        },
      }),
    ]);

    expect(messages).toMatchObject([
      {
        role: "human",
        content: "controlla @Chat",
        appReferences: [{ type: "app", app_id: "chat", label: "Chat" }],
      },
    ]);
  });

  it("preserves structured entity references on human messages", () => {
    const messages = eventsToMessages([
      event({
        event_type: "runtime.turn.queued",
        payload: {
          input_text: "controlla @Agency launch [ref:checklist/checklist/check_123]",
          app_references: [
            {
              type: "entity",
              app_id: "checklist",
              entity_type: "checklist",
              entity_id: "check_123",
              label: "Agency launch",
              summary: "1/3 checked",
              deep_link: "/app/checklist/checklists/check_123",
            },
          ],
        },
      }),
    ]);

    expect(messages).toMatchObject([
      {
        role: "human",
        appReferences: [
          {
            type: "entity",
            app_id: "checklist",
            entity_type: "checklist",
            entity_id: "check_123",
            label: "Agency launch",
          },
        ],
      },
    ]);
  });

  it("projects final provider output as an agent message", () => {
    const messages = eventsToMessages([
      event({
        event_type: "runtime.output.final",
        payload: { text: "## Result" },
      }),
    ]);
    expect(messages).toMatchObject([{ role: "agent", content: "## Result", status: "complete" }]);
  });

  it("uses complete final text when streamed hosted output stores only a suffix in text", () => {
    const messages = eventsToMessages([
      event({
        event_id: "delta-1",
        event_type: "runtime.output.delta",
        payload: { text: "Il cane " },
      }),
      event({
        event_id: "final-1",
        event_type: "runtime.output.final",
        payload: {
          text: "ballava.",
          complete_text: "Il cane ubriaco ballava.",
        },
      }),
    ]);

    expect(messages.filter((message) => message.role === "agent").map((message) => message.content).join("")).toBe("Il cane ubriaco ballava.");
  });

  it("projects structured final output without losing the fallback text", () => {
    const messages = eventsToMessages([
      event({
        event_type: "runtime.output.final",
        payload: { text: "Checklist ready", structured_content: { kind: "checklist.design", payload: { title: "Design" } } },
      }),
    ]);
    expect(messages).toMatchObject([
      { role: "structured", structuredContent: { kind: "checklist.design", payload: { title: "Design" } } },
      { role: "agent", content: "Checklist ready", status: "complete" },
    ]);
  });

  it("projects generic structured runtime output events", () => {
    const messages = eventsToMessages([
      event({
        event_id: "structured-1",
        event_type: "runtime.output.structured",
        payload: { structured_content: { kind: "dynamic.view.instance", payload: { id: "view_1" } } },
      }),
    ]);

    expect(messages).toMatchObject([
      { role: "structured", structuredContent: { kind: "dynamic.view.instance", payload: { id: "view_1" } } },
    ]);
  });

  it("creates widget-triggering structured content from workspace file links in agent text", () => {
    const messages = eventsToMessages([
      event({
        event_id: "final-with-file",
        event_type: "runtime.output.final",
        payload: { text: "I created [report.md](storage/generated/report.md)." },
      }),
    ]);

    expect(messages).toMatchObject([
      { role: "agent", content: "I created [report.md](storage/generated/report.md).", status: "complete" },
      {
        id: "turn-1:link-preview:final-with-file:0",
        role: "structured",
        structuredContent: {
          kind: "workspace.file.preview",
          payload: {
            source: "agent-link",
            label: "report.md",
            target: "storage/generated/report.md",
            workspace_relative_path: "storage/generated/report.md",
          },
        },
      },
    ]);
  });

  it("creates workspace file previews from completed streamed output", () => {
    const messages = eventsToMessages([
      event({
        event_id: "delta-with-file",
        event_type: "runtime.output.delta",
        payload: {
          text: "Ho preparato il report qui:\n\n[agents-cli-mcp-speed-report.md](/home/ubuntu/projects/maverick-v3/workspaces/default/storage/generated/agents-cli-mcp-speed-report.md:1)",
        },
      }),
      event({
        event_id: "final-empty",
        event_type: "runtime.output.final",
        payload: { text: "" },
      }),
    ]);

    expect(messages).toMatchObject([
      {
        role: "agent",
        content:
          "Ho preparato il report qui:\n\n[agents-cli-mcp-speed-report.md](/home/ubuntu/projects/maverick-v3/workspaces/default/storage/generated/agents-cli-mcp-speed-report.md:1)",
        status: "complete",
      },
      {
        role: "structured",
        structuredContent: {
          kind: "workspace.file.preview",
          payload: {
            label: "agents-cli-mcp-speed-report.md",
            target: "storage/generated/agents-cli-mcp-speed-report.md",
            workspace_relative_path: "storage/generated/agents-cli-mcp-speed-report.md",
          },
        },
      },
    ]);
  });

  it("extracts workspace file previews from hosted storage URLs without previewing generic web links", () => {
    const messages = eventsToMessages([
      event({
        event_id: "final-with-url",
        event_type: "runtime.output.final",
        payload: {
          text: "Guarda https://example.com/workspaces/default/storage/generated/final%20report.pdf e https://example.com/news",
        },
      }),
    ]);

    const previews = messages.filter((message) => message.role === "structured");
    expect(previews).toHaveLength(1);
    expect(previews[0].structuredContent).toMatchObject({
      kind: "workspace.file.preview",
      payload: {
        target: "https://example.com/workspaces/default/storage/generated/final%20report.pdf",
        workspace_relative_path: "storage/generated/final report.pdf",
      },
    });
  });

  it("normalizes local workspace paths without exposing absolute filesystem paths to widgets", () => {
    const messages = eventsToMessages([
      event({
        event_id: "final-with-local-path",
        event_type: "runtime.output.final",
        payload: { text: "File: /srv/maverick/workspaces/default/storage/generated/secret.pdf" },
      }),
    ]);

    const preview = messages.find((message) => message.role === "structured");
    expect(preview?.structuredContent).toMatchObject({
      kind: "workspace.file.preview",
      payload: {
        target: "storage/generated/secret.pdf",
        workspace_relative_path: "storage/generated/secret.pdf",
      },
    });
    expect(JSON.stringify(preview?.structuredContent?.payload)).not.toContain("/srv/maverick");
  });

  it("groups runtime tool call events under one tool-used message", () => {
    const messages = eventsToMessages([
      event({
        event_id: "tool-1",
        event_type: "runtime.tool_call.completed",
        payload: { name: "core.workspaces.list" },
      }),
      event({
        event_id: "tool-2",
        event_type: "runtime.tool_call.failed",
        payload: { name: "core.files.list", error: "denied" },
      }),
    ]);
    expect(messages).toMatchObject([
      {
        role: "tool",
        content: "Tool Used",
        status: "failed",
        toolCalls: [
          { name: "core.workspaces.list", status: "completed" },
          { name: "core.files.list", status: "failed" },
        ],
      },
    ]);
  });

  it("keeps projected inter-agent participant outputs in normal chat blocks", () => {
    const researcherProjection = {
      inter_agent_projection: "participant_runtime_event",
      inter_agent_run_id: "run-1",
      inter_agent_participant_id: "researcher",
      inter_agent_participant_label: "Researcher",
      inter_agent_participant_block_id: "researcher-block",
    };
    const reviewerProjection = {
      inter_agent_projection: "participant_runtime_event",
      inter_agent_run_id: "run-1",
      inter_agent_participant_id: "reviewer",
      inter_agent_participant_label: "Reviewer",
      inter_agent_participant_block_id: "reviewer-block",
    };

    const messages = eventsToMessages([
      event({
        event_id: "root-queued",
        event_type: "runtime.turn.queued",
        payload: { input_text: "Coordinate this.", client_message_id: "client-root" },
        created_at: "2026-04-19T00:00:00.000Z",
      }),
      event({
        event_id: "research-tool",
        event_type: "runtime.tool_call.completed",
        payload: { ...researcherProjection, name: "web_search" },
        created_at: "2026-04-19T00:00:01.000Z",
      }),
      event({
        event_id: "research-delta",
        event_type: "runtime.output.delta",
        payload: { ...researcherProjection, text: "Found the source. " },
        created_at: "2026-04-19T00:00:02.000Z",
      }),
      event({
        event_id: "research-final",
        event_type: "runtime.output.final",
        payload: { ...researcherProjection, text: "Found the source. It checks out." },
        created_at: "2026-04-19T00:00:03.000Z",
      }),
      event({
        event_id: "review-final",
        event_type: "runtime.output.final",
        payload: { ...reviewerProjection, text: "Reviewer agrees." },
        created_at: "2026-04-19T00:00:04.000Z",
      }),
    ]);

    expect(messages).toMatchObject([
      { id: "client-root", role: "human", content: "Coordinate this." },
      {
        id: "turn-1:inter-agent:researcher-block:tools:0",
        role: "tool",
        sourceLabel: "Researcher",
        sourceParticipantId: "researcher",
        sourceRunId: "run-1",
        toolCalls: [{ name: "web_search" }],
      },
      {
        id: "turn-1:inter-agent:researcher-block:agent:stream:0",
        role: "agent",
        sourceLabel: "Researcher",
        sourceParticipantId: "researcher",
        sourceRunId: "run-1",
        content: "Found the source. ",
        status: "complete",
      },
      {
        id: "turn-1:inter-agent:researcher-block:agent",
        role: "agent",
        sourceLabel: "Researcher",
        sourceParticipantId: "researcher",
        sourceRunId: "run-1",
        content: "It checks out.",
      },
      {
        id: "turn-1:inter-agent:reviewer-block:agent",
        role: "agent",
        sourceLabel: "Reviewer",
        sourceParticipantId: "reviewer",
        sourceRunId: "run-1",
        content: "Reviewer agrees.",
      },
    ]);
  });

  it("filters command execution output delta tool events from the chat transcript", () => {
    const messages = eventsToMessages([
      event({
        event_id: "tool-noise-1",
        event_type: "runtime.tool_call.completed",
        payload: {
          name: "tool",
          provider_event_type: "item.commandExecution.outputDelta",
          summary: ".",
        },
      }),
    ]);

    expect(messages).toEqual([]);
  });

  it("filters command execution telemetry tool events from the chat transcript", () => {
    const messages = eventsToMessages([
      event({
        event_id: "tool-noise-1",
        event_type: "runtime.tool_call.completed",
        payload: {
          name: "tool",
          provider_event_type: "item/commandExecution/outputDelta",
          summary: ".",
        },
      }),
      event({
        event_id: "tool-noise-2",
        event_type: "runtime.tool_call.completed",
        payload: {
          name: "tool",
          provider_event_type: "item.commandExecution.terminalInteraction",
          summary: "",
        },
      }),
    ]);

    expect(messages).toEqual([]);
  });

  it("filters command execution telemetry runtime steps from the chat transcript", () => {
    const messages = eventsToMessages([
      event({
        event_id: "step-noise-1",
        event_type: "runtime.step.updated",
        payload: {
          label: "item commandExecution outputDelta",
          provider_event_type: "item/commandExecution/outputDelta",
        },
      }),
      event({
        event_id: "step-noise-2",
        event_type: "runtime.step.updated",
        payload: {
          provider_event_type: "item.commandExecution.terminalInteraction",
        },
      }),
    ]);

    expect(messages).toEqual([]);
  });

  it("filters provider hook lifecycle noise from the chat transcript", () => {
    const messages = eventsToMessages([
      event({
        event_id: "hook-delta-1",
        event_type: "runtime.output.delta",
        payload: { text: "hook started\n" },
        created_at: "2026-04-19T00:00:01.000Z",
      }),
      event({
        event_id: "hook-step-1",
        event_type: "runtime.step.updated",
        payload: { label: "hook completed" },
        created_at: "2026-04-19T00:00:02.000Z",
      }),
      event({
        event_id: "agent-delta-1",
        event_type: "runtime.output.delta",
        payload: { text: "Checking files.\n" },
        created_at: "2026-04-19T00:00:03.000Z",
      }),
      event({
        event_id: "hook-delta-2",
        event_type: "runtime.output.delta",
        payload: { text: "hook completed\n" },
        created_at: "2026-04-19T00:00:04.000Z",
      }),
    ]);

    expect(messages).toMatchObject([{ role: "agent", content: "Checking files.\n" }]);
  });

  it("filters skills changed runtime updates from tool-used metadata", () => {
    const messages = eventsToMessages([
      event({
        event_id: "skills-1",
        event_type: "runtime.step.updated",
        payload: {
          label: "skills changed",
          provider_event_type: "skills.changed",
          skill_ids: ["generated-file-persistence"],
        },
      }),
    ]);

    expect(messages).toEqual([]);
  });

  it("suppresses empty goal updates without splitting tool groups", () => {
    const messages = eventsToMessages([
      event({
        event_id: "tool-1",
        event_type: "runtime.tool_call.completed",
        payload: { name: "functions.exec_command", command: "pwd" },
      }),
      event({
        event_id: "goal-empty",
        event_type: "runtime.step.updated",
        payload: { label: "thread goal updated", provider_event_type: "thread.goal.updated" },
      }),
      event({
        event_id: "tool-2",
        event_type: "runtime.tool_call.completed",
        payload: { name: "functions.exec_command", command: "git status -sb" },
      }),
    ]);

    expect(messages).toMatchObject([
      {
        role: "tool",
        toolCalls: [{ id: "tool-1" }, { id: "tool-2" }],
      },
    ]);
  });

  it("coalesces goal progress into one card with the latest usage", () => {
    const messages = eventsToMessages([
      event({
        event_id: "goal-active",
        event_type: "runtime.step.updated",
        payload: {
          label: "thread goal updated",
          provider_event_type: "thread.goal.updated",
          raw: {
            type: "thread.goal.updated",
            item: {
              threadId: "provider-thread-1",
              goal: { objective: "Ship the goal transcript fix", status: "active", tokensUsed: 0, timeUsedSeconds: 0 },
            },
          },
        },
      }),
      event({
        event_id: "tool-1",
        event_type: "runtime.tool_call.completed",
        payload: { name: "functions.exec_command", command: "npm test" },
      }),
      event({
        event_id: "goal-progress",
        event_type: "runtime.step.updated",
        payload: {
          label: "thread goal updated",
          provider_event_type: "thread.goal.updated",
          raw: {
            type: "thread.goal.updated",
            item: {
              threadId: "provider-thread-1",
              goal: { tokensUsed: 1892, timeUsedSeconds: 7 },
            },
          },
        },
      }),
      event({
        event_id: "tool-2",
        event_type: "runtime.tool_call.completed",
        payload: { name: "functions.exec_command", command: "npm run build" },
      }),
    ]);

    expect(messages.filter((message) => message.role === "step")).toHaveLength(1);
    expect(messages).toMatchObject([
      {
        role: "step",
        step: {
          detail: {
            raw: {
              item: {
                goal: {
                  objective: "Ship the goal transcript fix",
                  status: "active",
                  tokensUsed: 1892,
                  timeUsedSeconds: 7,
                },
              },
            },
          },
        },
      },
      {
        role: "tool",
        toolCalls: [{ id: "tool-1" }, { id: "tool-2" }],
      },
    ]);
  });

  it("removes an active goal card when the provider clears the goal", () => {
    const messages = eventsToMessages([
      event({
        event_id: "goal-active",
        event_type: "runtime.step.updated",
        payload: {
          provider_event_type: "thread.goal.updated",
          raw: { type: "thread.goal.updated", item: { goal: { objective: "Temporary goal", status: "active" } } },
        },
      }),
      event({
        event_id: "goal-cleared",
        event_type: "runtime.step.updated",
        payload: { provider_event_type: "thread.goal.cleared", raw: { type: "thread.goal.cleared", item: {} } },
      }),
    ]);

    expect(messages).toEqual([]);
  });

  it("keeps a terminal goal snapshot visible after the provider clears active state", () => {
    const messages = eventsToMessages([
      event({
        event_id: "goal-active",
        event_type: "runtime.step.updated",
        payload: {
          provider_event_type: "thread.goal.updated",
          raw: { type: "thread.goal.updated", item: { goal: { objective: "Finish the fix", status: "active" } } },
        },
      }),
      event({
        event_id: "goal-complete",
        event_type: "runtime.step.updated",
        payload: {
          provider_event_type: "thread.goal.updated",
          raw: { type: "thread.goal.updated", item: { goal: { status: "complete", tokensUsed: 2400 } } },
        },
      }),
      event({
        event_id: "goal-cleared",
        event_type: "runtime.step.updated",
        payload: { provider_event_type: "thread.goal.cleared", raw: { type: "thread.goal.cleared", item: {} } },
      }),
    ]);

    expect(messages).toMatchObject([
      {
        role: "step",
        step: {
          detail: {
            raw: {
              item: { goal: { objective: "Finish the fix", status: "complete", tokensUsed: 2400 } },
            },
          },
        },
      },
    ]);
  });

  it("starts a new tool-used group after a visible runtime update", () => {
    const messages = eventsToMessages([
      event({
        event_id: "tool-1",
        event_type: "runtime.tool_call.completed",
        payload: { name: "core.workspaces.list" },
        created_at: "2026-04-19T00:00:01.000Z",
      }),
      event({
        event_id: "tool-2",
        event_type: "runtime.tool_call.completed",
        payload: { name: "core.files.list" },
        created_at: "2026-04-19T00:00:02.000Z",
      }),
      event({
        event_id: "step-1",
        event_type: "runtime.step.updated",
        payload: { label: "Reading workspace files" },
        created_at: "2026-04-19T00:00:03.000Z",
      }),
      event({
        event_id: "tool-3",
        event_type: "runtime.tool_call.completed",
        payload: { name: "core.files.read" },
        created_at: "2026-04-19T00:00:04.000Z",
      }),
    ]);

    expect(messages).toMatchObject([
      {
        id: "turn-1:tools:0",
        role: "tool",
        toolCalls: [{ name: "core.workspaces.list" }, { name: "core.files.list" }],
      },
      { role: "step", step: { label: "Reading workspace files" } },
      {
        id: "turn-1:tools:1",
        role: "tool",
        toolCalls: [{ name: "core.files.read" }],
      },
    ]);
  });

  it("keeps repeated invocations of the same tool chronologically distinct", () => {
    const messages = eventsToMessages([
      event({
        event_id: "tool-1",
        event_type: "runtime.tool_call.completed",
        payload: { name: "functions.exec_command", command: "pwd" },
        created_at: "2026-04-19T00:00:01.000Z",
      }),
      event({
        event_id: "step-1",
        event_type: "runtime.step.updated",
        payload: { label: "Reading command output" },
        created_at: "2026-04-19T00:00:02.000Z",
      }),
      event({
        event_id: "tool-2",
        event_type: "runtime.tool_call.completed",
        payload: { name: "functions.exec_command", command: "pwd" },
        created_at: "2026-04-19T00:00:03.000Z",
      }),
    ]);

    expect(messages).toMatchObject([
      { id: "turn-1:tools:0", role: "tool", toolCalls: [{ id: "tool-1", name: "functions.exec_command" }] },
      { role: "step", step: { label: "Reading command output" } },
      { id: "turn-1:tools:1", role: "tool", toolCalls: [{ id: "tool-2", name: "functions.exec_command" }] },
    ]);
  });

  it("splits tool-used groups around streaming assistant updates", () => {
    const messages = eventsToMessages([
      event({
        event_id: "tool-1",
        event_type: "runtime.tool_call.completed",
        payload: { name: "functions.exec_command" },
        created_at: "2026-04-19T00:00:01.000Z",
      }),
      event({
        event_id: "delta-1",
        event_type: "runtime.output.delta",
        payload: { text: "Checking files." },
        created_at: "2026-04-19T00:00:02.000Z",
      }),
      event({
        event_id: "tool-2",
        event_type: "runtime.tool_call.completed",
        payload: { name: "functions.exec_command" },
        created_at: "2026-04-19T00:00:03.000Z",
      }),
    ]);

    expect(messages).toMatchObject([
      { id: "turn-1:tools:0", role: "tool", toolCalls: [{ id: "tool-1" }] },
      { role: "agent", content: "Checking files.", status: "pending" },
      { id: "turn-1:tools:1", role: "tool", toolCalls: [{ id: "tool-2" }] },
    ]);
  });

  it("closes active tool indicators when final output arrives", () => {
    const messages = eventsToMessages([
      event({
        event_id: "tool-1",
        event_type: "runtime.tool_call.started",
        payload: { name: "codex_apps", provider_event_type: "codex_apps.progress_activity" },
        created_at: "2026-04-19T00:00:01.000Z",
      }),
      event({
        event_id: "final-1",
        event_type: "runtime.output.final",
        payload: { text: "Done" },
        created_at: "2026-04-19T00:00:02.000Z",
      }),
    ]);

    expect(messages).toMatchObject([
      { role: "tool", toolCalls: [{ name: "codex_apps", status: "completed" }] },
      { role: "agent", content: "Done", status: "complete" },
    ]);
  });

  it("keeps the latest active tool indicator while the turn is still only a tool call", () => {
    const messages = eventsToMessages([
      event({
        event_id: "tool-1",
        event_type: "runtime.tool_call.started",
        payload: { name: "web_search" },
        created_at: "2026-04-19T00:00:01.000Z",
      }),
    ]);

    expect(messages).toMatchObject([{ role: "tool", toolCalls: [{ name: "web_search", status: "started" }] }]);
  });

  it("keeps tool-used sections at their event positions when runtime timestamps match", () => {
    const sameTimestamp = "2026-04-19T00:00:00.000Z";
    const messages = eventsToMessages([
      event({
        event_id: "queued-1",
        event_type: "runtime.turn.queued",
        payload: { input_text: "run it", client_message_id: "client-message-1" },
        created_at: sameTimestamp,
      }),
      event({
        event_id: "tool-1",
        event_type: "runtime.tool_call.completed",
        payload: { name: "functions.exec_command" },
        created_at: sameTimestamp,
      }),
      event({
        event_id: "step-1",
        event_type: "runtime.step.updated",
        payload: { label: "Reading command output" },
        created_at: sameTimestamp,
      }),
      event({
        event_id: "tool-2",
        event_type: "runtime.tool_call.completed",
        payload: { name: "functions.exec_command" },
        created_at: sameTimestamp,
      }),
      event({
        event_id: "step-2",
        event_type: "runtime.step.updated",
        payload: { label: "Inspecting results" },
        created_at: sameTimestamp,
      }),
      event({
        event_id: "tool-3",
        event_type: "runtime.tool_call.completed",
        payload: { name: "functions.exec_command" },
        created_at: sameTimestamp,
      }),
      event({
        event_id: "final-1",
        event_type: "runtime.output.final",
        payload: { text: "done" },
        created_at: sameTimestamp,
      }),
    ]);

    expect(messages.map((message) => message.id)).toEqual([
      "client-message-1",
      "turn-1:tools:0",
      "turn-1:step:step-1",
      "turn-1:tools:1",
      "turn-1:step:step-2",
      "turn-1:tools:2",
      "turn-1:agent",
    ]);
  });

  it("deduplicates started and completed events for the same tool command", () => {
    const command = "/bin/bash -lc \"pwd && rg --files\"";
    const messages = eventsToMessages([
      event({
        event_id: "tool-started",
        event_type: "runtime.tool_call.started",
        payload: { name: command, command, tool_call_id: "call-1" },
      }),
      event({
        event_id: "tool-completed",
        event_type: "runtime.tool_call.completed",
        payload: { name: command, command, exit_code: 0, tool_call_id: "call-1" },
      }),
    ]);
    expect(messages).toMatchObject([
      {
        role: "tool",
        toolCalls: [{ status: "completed", detail: { exit_code: 0 } }],
      },
    ]);
    expect(messages[0].toolCalls).toHaveLength(1);
  });

  it("merges file change lifecycle events even when one event is missing the provider id", () => {
    const messages = eventsToMessages([
      event({
        event_id: "file-change-started",
        event_type: "runtime.tool_call.started",
        payload: {
          name: "file_change",
          summary: "Applying file changes",
          tool_kind: "file_change",
        },
      }),
      event({
        event_id: "file-change-updated",
        event_type: "runtime.tool_call.updated",
        payload: {
          name: "file_change",
          output: "Success. Updated the following files:\nM apps/chat/main.tsx",
          tool_call_id: "fc-1",
          tool_kind: "file_change",
        },
      }),
      event({
        event_id: "file-change-completed",
        event_type: "runtime.tool_call.completed",
        payload: {
          changes: [{ path: "apps/chat/main.tsx", changeType: "edit" }],
          name: "file_change",
          summary: "Applied file changes",
          tool_call_id: "fc-1",
          tool_kind: "file_change",
        },
      }),
    ]);

    expect(messages).toMatchObject([
      {
        role: "tool",
        toolCalls: [
          {
            name: "file_change",
            status: "completed",
            detail: {
              changes: [{ path: "apps/chat/main.tsx", changeType: "edit" }],
              output: "Success. Updated the following files:\nM apps/chat/main.tsx",
            },
          },
        ],
      },
    ]);
    expect(messages[0].toolCalls).toHaveLength(1);
  });

  it("filters noisy provider lifecycle steps from the chat transcript", () => {
    const messages = eventsToMessages([
      event({
        event_id: "step-1",
        event_type: "runtime.step.updated",
        payload: { label: "Reading additional input from stdin..." },
      }),
      event({
        event_id: "step-2",
        event_type: "runtime.step.updated",
        payload: { label: "turn started" },
      }),
      event({
        event_id: "step-3",
        event_type: "runtime.step.updated",
        payload: { label: "turn diff updated" },
      }),
      event({
        event_id: "step-4",
        event_type: "runtime.step.updated",
        payload: { label: "Reading workspace" },
      }),
    ]);
    expect(messages).toMatchObject([{ role: "step", step: { label: "Reading workspace" } }]);
  });

  it("filters raw provider JSON step labels from persisted transcripts", () => {
    const messages = eventsToMessages([
      event({
        event_id: "step-json",
        event_type: "runtime.step.updated",
        payload: { label: '{"type":"item.started","item":{"type":"command_execution","command":"rg --files"}}' },
      }),
      event({
        event_id: "step-real",
        event_type: "runtime.step.updated",
        payload: { label: "Reading workspace" },
      }),
    ]);
    expect(messages).toMatchObject([{ role: "step", step: { label: "Reading workspace" } }]);
  });

  it("projects runtime step events as step messages", () => {
    const messages = eventsToMessages([
      event({
        event_type: "runtime.step.updated",
        payload: { label: "Reading workspace" },
      }),
    ]);
    expect(messages).toMatchObject([{ role: "step", step: { label: "Reading workspace" } }]);
  });

  it("preserves streamed output segment positions after a final answer exists", () => {
    const streaming = eventsToMessages([
      event({
        event_type: "runtime.output.delta",
        payload: { text: "partial" },
      }),
    ]);
    expect(streaming).toMatchObject([{ role: "agent", content: "partial", status: "pending" }]);

    const completed = eventsToMessages([
      event({
        event_id: "event-delta",
        event_type: "runtime.output.delta",
        payload: { text: "partial" },
      }),
      event({
        event_id: "event-final",
        event_type: "runtime.output.final",
        payload: { text: "final" },
      }),
    ]);
    expect(completed).toMatchObject([
      { id: "turn-1:agent:stream:0", role: "agent", content: "partial", status: "complete" },
      { id: "turn-1:agent", role: "agent", content: "final", status: "complete" },
    ]);
  });

  it("keeps tool-used blocks interleaved with streamed assistant updates after completion", () => {
    const messages = eventsToMessages([
      event({
        event_id: "tool-1",
        event_type: "runtime.tool_call.completed",
        payload: { name: "web_search" },
        created_at: "2026-04-19T00:00:01.000Z",
      }),
      event({
        event_id: "delta-1",
        event_type: "runtime.output.delta",
        payload: { text: "Using web search. " },
        created_at: "2026-04-19T00:00:02.000Z",
      }),
      event({
        event_id: "tool-2",
        event_type: "runtime.tool_call.completed",
        payload: { name: "functions.exec_command" },
        created_at: "2026-04-19T00:00:03.000Z",
      }),
      event({
        event_id: "delta-2",
        event_type: "runtime.output.delta",
        payload: { text: "Writing the report." },
        created_at: "2026-04-19T00:00:04.000Z",
      }),
      event({
        event_id: "tool-3",
        event_type: "runtime.tool_call.completed",
        payload: { name: "functions.exec_command" },
        created_at: "2026-04-19T00:00:05.000Z",
      }),
      event({
        event_id: "final-1",
        event_type: "runtime.output.final",
        payload: { text: "Using web search. Writing the report." },
        created_at: "2026-04-19T00:00:06.000Z",
      }),
    ]);

    expect(messages.map((message) => message.id)).toEqual([
      "turn-1:tools:0",
      "turn-1:agent:stream:0",
      "turn-1:tools:1",
      "turn-1:agent:stream:1",
      "turn-1:tools:2",
    ]);
    expect(messages).toMatchObject([
      { role: "tool", toolCalls: [{ id: "tool-1" }] },
      { role: "agent", content: "Using web search. ", status: "complete" },
      { role: "tool", toolCalls: [{ id: "tool-2" }] },
      { role: "agent", content: "Writing the report.", status: "complete" },
      { role: "tool", toolCalls: [{ id: "tool-3" }] },
    ]);
  });

  it("uses final output only for the missing suffix after streamed output", () => {
    const messages = eventsToMessages([
      event({
        event_id: "delta-1",
        event_type: "runtime.output.delta",
        payload: { text: "First part. " },
        created_at: "2026-04-19T00:00:01.000Z",
      }),
      event({
        event_id: "final-1",
        event_type: "runtime.output.final",
        payload: { text: "First part. Final part." },
        created_at: "2026-04-19T00:00:02.000Z",
      }),
    ]);

    expect(messages).toMatchObject([
      { id: "turn-1:agent:stream:0", role: "agent", content: "First part. ", status: "complete" },
      { id: "turn-1:agent", role: "agent", content: "Final part.", status: "complete" },
    ]);
  });

  it("deduplicates final output prefixes when only whitespace changed", () => {
    const messages = eventsToMessages([
      event({
        event_id: "delta-1",
        event_type: "runtime.output.delta",
        payload: { text: "First part. " },
        created_at: "2026-04-19T00:00:01.000Z",
      }),
      event({
        event_id: "final-1",
        event_type: "runtime.output.final",
        payload: { text: "First part.\n\nFinal part." },
        created_at: "2026-04-19T00:00:02.000Z",
      }),
    ]);

    expect(messages).toMatchObject([
      { id: "turn-1:agent:stream:0", role: "agent", content: "First part. ", status: "complete" },
      { id: "turn-1:agent", role: "agent", content: "Final part.", status: "complete" },
    ]);
  });

  it("replaces partial streamed tail with complete final text for bounded history snapshots", () => {
    const messages = eventsToMessages([
      event({
        event_id: "delta-tail",
        event_type: "runtime.output.delta",
        payload: { text: "Tail visible in the bounded replay." },
        created_at: "2026-04-19T00:00:01.000Z",
      }),
      event({
        event_id: "final-1",
        event_type: "runtime.output.final",
        payload: {
          text: "",
          complete_text: "Full answer starts before the bounded replay. Tail visible in the bounded replay.",
        },
        created_at: "2026-04-19T00:00:02.000Z",
      }),
    ]);

    expect(messages.filter((message) => message.role === "agent")).toMatchObject([
      {
        id: "turn-1:agent",
        content: "Full answer starts before the bounded replay. Tail visible in the bounded replay.",
        status: "complete",
      },
    ]);
  });

  it("keeps streamed progress when final text is a separate answer", () => {
    const messages = eventsToMessages([
      event({
        event_id: "delta-progress",
        event_type: "runtime.output.delta",
        payload: { text: "Checking the workspace." },
        created_at: "2026-04-19T00:00:01.000Z",
      }),
      event({
        event_id: "final-1",
        event_type: "runtime.output.final",
        payload: { text: "Final answer only.", complete_text: "Final answer only." },
        created_at: "2026-04-19T00:00:02.000Z",
      }),
    ]);

    expect(messages.filter((message) => message.role === "agent")).toMatchObject([
      { id: "turn-1:agent:stream:0", content: "Checking the workspace.", status: "complete" },
      { id: "turn-1:agent", content: "Final answer only.", status: "complete" },
    ]);
  });

  it("concatenates streaming deltas without injecting newlines or trimming spaces", () => {
    const messages = eventsToMessages([
      event({
        event_id: "delta-1",
        event_type: "runtime.output.delta",
        payload: { text: "How" },
        created_at: "2026-04-19T00:00:01.000Z",
      }),
      event({
        event_id: "delta-2",
        event_type: "runtime.output.delta",
        payload: { text: " are" },
        created_at: "2026-04-19T00:00:02.000Z",
      }),
      event({
        event_id: "delta-3",
        event_type: "runtime.output.delta",
        payload: { text: " you?" },
        created_at: "2026-04-19T00:00:03.000Z",
      }),
    ]);

    expect(messages).toMatchObject([{ role: "agent", content: "How are you?", status: "pending" }]);
  });

  it("projects cancelled turns as system messages", () => {
    const messages = eventsToMessages([
      event({
        event_type: "runtime.turn.cancelled",
        payload: { reason: "interrupted_by_user" },
      }),
    ]);
    expect(messages).toMatchObject([{ role: "system", content: "interrupted by user", status: "failed" }]);
  });
});
