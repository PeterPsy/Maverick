import { describe, expect, it } from "vitest";
import type { ChatThread } from "../api/client";
import { interAgentComposerBudgetLabel, interAgentRunPayload, type AgentRuntimeConfig } from "./useMessageSubmission";

function thread(): ChatThread {
  return {
    thread_id: "thread-1",
    runtime_session_id: "session-1",
    title: "Thread",
    agent_label: "General agent",
    agent_type_id: "general-agent",
    agent_role_id: "",
    source_app_id: "chat",
    system_prompt: "",
    project_id: null,
    archived: false,
    availability: "free",
    created_at: "2026-06-17T10:00:00Z",
    updated_at: "2026-06-17T10:00:00Z",
  };
}

function agentRuntimeConfig(): AgentRuntimeConfig {
  return {
    agent_id: "Researcher",
    agent_role_id: "role-researcher",
    agent_type_id: "agent-researcher",
    skill_catalog_app_id: "skills",
    skill_ids: ["storage", "browser"],
    source_app_id: "agents",
    system_prompt: "Research with citations.",
    title: "Researcher",
  };
}

describe("interAgentRunPayload", () => {
  it("carries the selected agent prompt and skills as an explicit snapshot", () => {
    const payload = interAgentRunPayload({
      agentRuntimeConfig: agentRuntimeConfig(),
      clientMessageId: "client-1",
      mode: "auto",
      thread: thread(),
    });

    expect(payload.participants[1]).toMatchObject({
      agent_type_id: "agent-researcher",
      agent_snapshot: {
        agent_type_id: "agent-researcher",
        label: "Researcher",
        system_prompt: "Research with citations.",
        skill_catalog_app_id: "skills",
        skill_ids: ["storage", "browser"],
      },
    });
    expect(payload.visibility_level).toBe("detail");
    expect(payload.edges).toEqual([
      {
        source_id: "orchestrator",
        target_id: "assistant",
        kind: "delegated",
        label: "Researcher",
      },
    ]);
    expect(payload.mode).toBe("manager_tools");
    expect(payload.budget).toMatchObject({
      max_participants: 2,
      max_concurrent_participants: 1,
      max_total_turns: 1,
      max_turns_per_participant: 1,
      max_tool_calls: 1,
    });
  });

  it("keeps selected skills in the snapshot when the agent prompt is empty", () => {
    const config = { ...agentRuntimeConfig(), system_prompt: "" };
    const payload = interAgentRunPayload({
      agentRuntimeConfig: config,
      clientMessageId: "client-1",
      mode: "auto",
      thread: thread(),
    });

    expect(payload.participants[1]).toMatchObject({
      agent_snapshot: {
        system_prompt: "",
        skill_ids: ["storage", "browser"],
      },
    });
  });

  it("builds a real two-worker review graph for multi mode", () => {
    const payload = interAgentRunPayload({
      agentRuntimeConfig: agentRuntimeConfig(),
      clientMessageId: "client-1",
      mode: "multi",
      thread: thread(),
    });

    expect(payload.mode).toBe("sequential");
    expect(payload.participants.map((participant) => participant.participant_id)).toEqual(["orchestrator", "implementer", "reviewer"]);
    expect(payload.participants[1]).toMatchObject({
      participant_id: "implementer",
      label: "Implementer",
      agent_snapshot: {
        label: "Implementer",
        system_prompt: "Research with citations.",
      },
    });
    expect(payload.participants[2]).toMatchObject({
      participant_id: "reviewer",
      label: "Reviewer",
      agent_snapshot: {
        label: "Reviewer",
        skill_ids: ["storage", "browser"],
      },
    });
    expect(payload.edges).toEqual([
      {
        source_id: "orchestrator",
        target_id: "implementer",
        kind: "delegated",
        label: "Implementation",
      },
      {
        source_id: "implementer",
        target_id: "reviewer",
        kind: "reviewed_by",
        label: "Review",
      },
      {
        source_id: "reviewer",
        target_id: "orchestrator",
        kind: "produced",
        label: "Final review",
      },
    ]);
    expect(payload.budget).toMatchObject({
      max_participants: 3,
      max_concurrent_participants: 1,
      max_total_turns: 2,
      max_turns_per_participant: 1,
      max_tool_calls: 2,
    });
  });

  it("uses budget copy that matches actual worker counts", () => {
    expect(interAgentComposerBudgetLabel("off")).toBe("");
    expect(interAgentComposerBudgetLabel("auto")).toBe("1 worker · 1 turn · 1 tool call");
    expect(interAgentComposerBudgetLabel("multi")).toBe("2 workers · 2 turns · 2 tool calls");
  });
});
