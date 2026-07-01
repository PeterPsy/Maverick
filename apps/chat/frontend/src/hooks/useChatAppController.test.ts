import { describe, expect, it } from "vitest";
import type { ChatThread, ProviderItem, RuntimeSession, RuntimeTurn } from "../api/client";
import { isActiveRuntimeTurnBusyForThread, providersForComposer, selectedProviderForSession } from "./useChatAppController";

function thread(availability: string, overrides: Partial<ChatThread> = {}): ChatThread {
  return {
    thread_id: "thread-1",
    runtime_session_id: "session-1",
    title: "Thread",
    agent_label: "chat",
    agent_type_id: "",
    agent_role_id: "",
    source_app_id: "chat",
    system_prompt: "",
    project_id: null,
    archived: false,
    availability,
    created_at: "2026-04-19T10:00:00Z",
    updated_at: "2026-04-19T10:00:00Z",
    ...overrides,
  };
}

function turn(status: string): RuntimeTurn {
  return {
    turn_id: "turn-1",
    session_id: "session-1",
    workspace_id: "default",
    status,
    input_text: "work",
    failure_reason: null,
    created_at: "2026-04-19T10:00:00Z",
    updated_at: "2026-04-19T10:00:01Z",
  };
}

describe("chat runtime busy guard", () => {
  it("treats active turns as busy only while the selected thread is busy", () => {
    expect(isActiveRuntimeTurnBusyForThread(turn("active"), thread("active"))).toBe(true);
    expect(isActiveRuntimeTurnBusyForThread(turn("queued"), thread("queued"))).toBe(true);
    expect(isActiveRuntimeTurnBusyForThread(turn("active"), thread("free"))).toBe(false);
  });

  it("does not treat terminal turns as busy", () => {
    expect(isActiveRuntimeTurnBusyForThread(turn("completed"), thread("active"))).toBe(false);
    expect(isActiveRuntimeTurnBusyForThread(turn("failed"), thread("busy"))).toBe(false);
  });

  it("keeps existing busy behavior when the thread is not selected yet", () => {
    expect(isActiveRuntimeTurnBusyForThread(turn("active"), null)).toBe(true);
  });
});

function provider(overrides: Partial<ProviderItem>): ProviderItem {
  return {
    provider_id: "codex",
    label: "Codex",
    description: "",
    status: "active",
    default_model_family: null,
    ...overrides,
  };
}

function session(overrides: Partial<RuntimeSession>): RuntimeSession {
  return {
    session_id: "session-1",
    workspace_id: "default",
    agent_id: "chat",
    status: "running",
    effective_mode: "sandbox",
    provider_id: "codex",
    ...overrides,
  };
}

describe("selectedProviderForSession", () => {
  it("uses the exact hosted provider and model persisted on the active session", () => {
    const providers = [
      provider({
        provider_id: "hosted:openrouter:model-a",
        label: "Model A - OpenRouter",
        provider_role: "model_provider",
        kind: "hosted_api",
        hosted_provider_id: "openrouter",
        hosted_model_id: "model-a",
      }),
      provider({
        provider_id: "hosted:openrouter:model-b",
        label: "Model B - OpenRouter",
        provider_role: "model_provider",
        kind: "hosted_api",
        hosted_provider_id: "openrouter",
        hosted_model_id: "model-b",
      }),
    ];

    const selected = selectedProviderForSession({
      activeProviderId: "codex",
      activeSession: session({
        runtime_mode: "plain_hosted_chat",
        hosted_provider_id: "openrouter",
        hosted_model_id: "model-b",
      }),
      activeThread: thread("free"),
      providers,
    });

    expect(selected?.label).toBe("Model B - OpenRouter");
    expect(selected?.hosted_model_id).toBe("model-b");
  });

  it("creates a readable locked hosted label when provider data lacks the exact model option", () => {
    const selected = selectedProviderForSession({
      activeProviderId: "codex",
      activeSession: session({
        runtime_mode: "plain_hosted_chat",
        hosted_provider_id: "google-ai-studio",
        hosted_model_id: "gemini-3.5-flash",
      }),
      activeThread: thread("free"),
      providers: [
        provider({
          provider_id: "hosted:google-ai-studio:gemini-current",
          label: "Gemini Current - Google AI Studio",
          provider_role: "model_provider",
          kind: "hosted_api",
          hosted_provider_id: "google-ai-studio",
          hosted_model_id: "gemini-current",
        }),
      ],
    });

    expect(selected?.hosted_model_id).toBe("gemini-3.5-flash");
    expect(selected?.label).toBe("gemini-3.5-flash - Gemini Current - Google AI Studio");
  });

  it("uses provider_id for existing agentic sessions", () => {
    const selected = selectedProviderForSession({
      activeProviderId: "hosted:openrouter:model-a",
      activeSession: session({ runtime_mode: "agentic", provider_id: "codex" }),
      activeThread: thread("free"),
      providers: [provider({ provider_id: "codex", label: "Codex" }), provider({ provider_id: "other", label: "Other" })],
    });

    expect(selected?.provider_id).toBe("codex");
  });

  it("does not show the global hosted model while an existing agentic thread session is loading", () => {
    const selected = selectedProviderForSession({
      activeProviderId: "hosted:openrouter:model-a",
      activeSession: null,
      activeThread: thread("free", { runtime_mode: "agentic", provider_id: "codex" }),
      providers: [
        provider({ provider_id: "hosted:openrouter:model-a", label: "Gemma", provider_role: "model_provider", kind: "hosted_api" }),
        provider({ provider_id: "codex", label: "Codex", provider_role: "runtime_engine" }),
      ],
    });

    expect(selected?.provider_id).toBe("codex");
  });

  it("uses hosted runtime metadata from the active thread while the session snapshot is loading", () => {
    const selected = selectedProviderForSession({
      activeProviderId: "codex",
      activeSession: null,
      activeThread: thread("free", {
        runtime_mode: "plain_hosted_chat",
        hosted_provider_id: "openrouter",
        hosted_model_id: "model-a",
      }),
      providers: [
        provider({ provider_id: "codex", label: "Codex", provider_role: "runtime_engine" }),
        provider({
          provider_id: "hosted:openrouter:model-a",
          label: "Model A - OpenRouter",
          provider_role: "model_provider",
          kind: "hosted_api",
          hosted_provider_id: "openrouter",
          hosted_model_id: "model-a",
        }),
      ],
    });

    expect(selected?.provider_id).toBe("hosted:openrouter:model-a");
  });

  it("includes synthetic selected providers in composer options", () => {
    const loadedProviders = [provider({ provider_id: "hosted:google-ai-studio:gemini-current", label: "Gemini Current" })];
    const selected = provider({
      provider_id: "hosted-session:google-ai-studio:gemini-3.5-flash",
      label: "gemini-3.5-flash - Gemini Current",
      hosted_provider_id: "google-ai-studio",
      hosted_model_id: "gemini-3.5-flash",
    });

    expect(providersForComposer(loadedProviders, selected).map((item) => item.provider_id)).toEqual([
      "hosted-session:google-ai-studio:gemini-3.5-flash",
      "hosted:google-ai-studio:gemini-current",
    ]);
  });
});
