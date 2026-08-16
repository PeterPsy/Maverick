import { describe, expect, it } from "vitest";
import { interAgentComposerBudgetLabel, interAgentOrchestrationIntent, runtimeSessionOptionsForNewChat } from "./useMessageSubmission";

describe("interAgentOrchestrationIntent", () => {
  it("sends only the root turn identity and orchestration policy", () => {
    const payload = interAgentOrchestrationIntent({
      clientMessageId: "client-1",
      mode: "multi",
      rootRuntimeSessionId: "session-1",
      sourceRuntimeTurnId: "turn-1",
    });

    expect(payload).toEqual({
      root_runtime_session_id: "session-1",
      source_runtime_turn_id: "turn-1",
      policy: "multi",
      idempotency_key: "chat:client-1:orchestration:multi",
    });
    expect(payload).not.toHaveProperty("participants");
    expect(payload).not.toHaveProperty("edges");
    expect(payload).not.toHaveProperty("budget");
    expect(payload).not.toHaveProperty("participant_inputs");
  });

  it("describes dynamic scheduling instead of static worker counts", () => {
    expect(interAgentComposerBudgetLabel("off")).toBe("");
    expect(interAgentComposerBudgetLabel("auto")).toBe("Dynamic plan · quality gated");
    expect(interAgentComposerBudgetLabel("multi")).toBe("Implement · review · revise");
    expect(interAgentComposerBudgetLabel("group_chat")).toBe("Dynamic group · quality gated");
  });
});

describe("runtimeSessionOptionsForNewChat", () => {
  it("uses explicit skill activation for a new generalist chat", () => {
    const options = runtimeSessionOptionsForNewChat({ agentRuntimeConfig: null, draftChat: null, systemPrompt: "" });
    expect(options.skill_activation_mode).toBe("explicit");
  });

  it("preserves implicit activation for legacy specialized agent definitions", () => {
    const options = runtimeSessionOptionsForNewChat({
      agentRuntimeConfig: {
        agent_id: "Reviewer",
        agent_role_id: "reviewer",
        agent_type_id: "reviewer",
        skill_catalog_app_id: "skills",
        skill_ids: ["review-skill"],
        source_app_id: "agents",
        system_prompt: "Review.",
        title: "Reviewer",
      },
      draftChat: null,
      systemPrompt: "Review.",
    });
    expect(options.skill_activation_mode).toBe("implicit");
  });
});
