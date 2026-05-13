import { describe, expect, it } from "vitest";
import type { RuntimeEvent } from "../api/client";
import { eventsToMessages } from "./transcript";

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
  it("projects one human message from a queued runtime turn", () => {
    const messages = eventsToMessages([
      event({
        event_type: "runtime.turn.queued",
        payload: { input_text: "hello", client_message_id: "client-message-1" },
      }),
    ]);
    expect(messages).toMatchObject([{ id: "client-message-1", role: "human", content: "hello", status: "complete" }]);
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
        payload: { text: "Ho creato [report.md](storage/generated/report.md)." },
      }),
    ]);

    expect(messages).toMatchObject([
      { role: "agent", content: "Ho creato [report.md](storage/generated/report.md).", status: "complete" },
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
        payload: { text: "Controllo i file." },
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
      { role: "agent", content: "Controllo i file.", status: "pending" },
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
        payload: { text: "Uso una ricerca web. " },
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
        payload: { text: "Scrivo il report." },
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
        payload: { text: "Uso una ricerca web. Scrivo il report." },
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
      { role: "agent", content: "Uso una ricerca web. ", status: "complete" },
      { role: "tool", toolCalls: [{ id: "tool-2" }] },
      { role: "agent", content: "Scrivo il report.", status: "complete" },
      { role: "tool", toolCalls: [{ id: "tool-3" }] },
    ]);
  });

  it("uses final output only for the missing suffix after streamed output", () => {
    const messages = eventsToMessages([
      event({
        event_id: "delta-1",
        event_type: "runtime.output.delta",
        payload: { text: "Prima parte. " },
        created_at: "2026-04-19T00:00:01.000Z",
      }),
      event({
        event_id: "final-1",
        event_type: "runtime.output.final",
        payload: { text: "Prima parte. Parte finale." },
        created_at: "2026-04-19T00:00:02.000Z",
      }),
    ]);

    expect(messages).toMatchObject([
      { id: "turn-1:agent:stream:0", role: "agent", content: "Prima parte. ", status: "complete" },
      { id: "turn-1:agent", role: "agent", content: "Parte finale.", status: "complete" },
    ]);
  });

  it("deduplicates final output prefixes when only whitespace changed", () => {
    const messages = eventsToMessages([
      event({
        event_id: "delta-1",
        event_type: "runtime.output.delta",
        payload: { text: "Prima parte. " },
        created_at: "2026-04-19T00:00:01.000Z",
      }),
      event({
        event_id: "final-1",
        event_type: "runtime.output.final",
        payload: { text: "Prima parte.\n\nParte finale." },
        created_at: "2026-04-19T00:00:02.000Z",
      }),
    ]);

    expect(messages).toMatchObject([
      { id: "turn-1:agent:stream:0", role: "agent", content: "Prima parte. ", status: "complete" },
      { id: "turn-1:agent", role: "agent", content: "Parte finale.", status: "complete" },
    ]);
  });

  it("concatenates streaming deltas without injecting newlines or trimming spaces", () => {
    const messages = eventsToMessages([
      event({
        event_id: "delta-1",
        event_type: "runtime.output.delta",
        payload: { text: "Ciao" },
        created_at: "2026-04-19T00:00:01.000Z",
      }),
      event({
        event_id: "delta-2",
        event_type: "runtime.output.delta",
        payload: { text: ", come" },
        created_at: "2026-04-19T00:00:02.000Z",
      }),
      event({
        event_id: "delta-3",
        event_type: "runtime.output.delta",
        payload: { text: " va?" },
        created_at: "2026-04-19T00:00:03.000Z",
      }),
    ]);

    expect(messages).toMatchObject([{ role: "agent", content: "Ciao, come va?", status: "pending" }]);
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
