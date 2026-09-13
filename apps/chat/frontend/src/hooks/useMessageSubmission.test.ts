import { describe, expect, it } from "vitest";
import type { RuntimeSession } from "../api/client";
import {
  interAgentComposerBudgetLabel,
  interAgentOrchestrationIntent,
  preparedRuntimeSessionFromResponse,
  preparedRuntimeSessionIsReady,
  runtimeSessionOptionsForNewChat,
} from "./useMessageSubmission";

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

  it("reduces a Device Use chat to the Codex mono-agent envelope", () => {
    const options = runtimeSessionOptionsForNewChat({
      agentRuntimeConfig: {
        agent_id: "chat",
        agent_role_id: "",
        agent_type_id: "",
        skill_catalog_app_id: "",
        skill_ids: [],
        skill_activation_mode: "explicit",
        source_app_id: "chat",
        system_prompt: "",
        title: "GPT-6 Astra",
        runtime_mode: "agentic",
        workspace_profile_binding_id: "binding-astra",
        reasoning_effort: "high",
      },
      deviceUseActivationId: "01234567-89ab-cdef-0123-456789abcdef",
      draftChat: null,
      systemPrompt: "must not enter the device thread",
    });

    expect(options).toMatchObject({
      agent_id: "chat",
      source_app_id: "chat",
      agent_role_id: "",
      agent_type_id: "",
      skill_ids: [],
      skill_activation_mode: "explicit",
      runtime_mode: "agentic",
      workspace_profile_binding_id: "binding-astra",
      reasoning_effort: "high",
      device_use_activation_id: "01234567-89ab-cdef-0123-456789abcdef",
    });
    expect(options.system_prompt).toBeUndefined();
  });
});

describe("prepared runtime sessions", () => {
  it("retains the session id when the two-second prewarm wait returns pending", () => {
    const pending = {
      session_id: "prepared-pending",
      prewarm_status: "pending",
      prewarm_completed: false,
      provider_thread_ready: false,
      runtime_ready: false,
    } as RuntimeSession;

    const prepared = preparedRuntimeSessionFromResponse("draft:active", "config", pending);

    expect(prepared.session.session_id).toBe("prepared-pending");
    expect(preparedRuntimeSessionIsReady(prepared.session)).toBe(false);
  });

  it("reports a prepared session ready only after runtime prewarm completes", () => {
    const ready = {
      session_id: "prepared-ready",
      prewarm_completed: true,
      provider_thread_ready: true,
      runtime_ready: true,
    } as RuntimeSession;

    expect(preparedRuntimeSessionIsReady(ready)).toBe(true);
  });
});
