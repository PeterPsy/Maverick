import { describe, expect, it } from "vitest";
import type { ChatThread } from "../api/client";
import { interAgentRunPayload, type AgentRuntimeConfig } from "./useMessageSubmission";

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
});
