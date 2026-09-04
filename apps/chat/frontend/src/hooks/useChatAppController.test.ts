import { describe, expect, it } from "vitest";
import type { ChatThread, ProviderItem, RuntimeSession, RuntimeTurn } from "../api/client";
import {
  isActiveRuntimeTurnBusyForThread,
  providersForComposer,
  runtimeAdmissionBlockMessage,
  selectedProviderForSession,
} from "./useChatAppController";

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

describe("runtime admission status", () => {
  it("shows explicit containment and quarantine causes", () => {
    const quarantineMessage = runtimeAdmissionBlockMessage(session({
      status: "recovery_required",
      recovery_reason_code: "private:/srv/runtime/token=do-not-render",
    }));
    expect(quarantineMessage).toContain("quarantined");
    expect(quarantineMessage).toContain("state is ambiguous");
    expect(quarantineMessage).not.toContain("do-not-render");
    expect(runtimeAdmissionBlockMessage(session({
      agentic_containment: {
        status: "NO-GO",
        reason_code: "hosted_agent_runtime_disabled",
      },
    }))).toContain("contained (NO-GO)");
  });

  it("blocks unsafe and missing-thread sessions with actionable copy", () => {
    expect(runtimeAdmissionBlockMessage(session({
      runtime_admission: {
        status: "upgrade_required",
        reason_code: "runtime_profile_upgrade_required",
        detail_code: "runtime_profile_upgrade_legacy_authority_unproven",
        source_profile_revision: "2",
        target_profile_revision: null,
        provider_thread_available: true,
      },
    }))).toContain("cannot be upgraded automatically");
    expect(runtimeAdmissionBlockMessage(session({
      runtime_admission: {
        status: "provider_thread_missing",
        reason_code: "runtime_profile_upgrade_required",
        detail_code: "provider_thread_missing",
        source_profile_revision: "5",
        target_profile_revision: null,
        provider_thread_available: false,
      },
    }))).toContain("provider conversation");
  });

  it("keeps direct and compatible-upgrade sessions interactive", () => {
    expect(runtimeAdmissionBlockMessage(session({
      runtime_admission: {
        status: "compatible_upgrade",
        reason_code: "runtime_profile_upgrade_compatible",
        detail_code: "adapter_artifact_mismatch",
        source_profile_revision: "5",
        target_profile_revision: "7",
        provider_thread_available: true,
      },
    }))).toBeNull();
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

  it("keeps a missing local pinned option on the Codex rollout-skew fallback", () => {
    const selected = selectedProviderForSession({
      activeProviderId: "codex",
      activeSession: session({
        runtime_mode: "agentic",
        provider_id: "codex",
        execution_binding: {
          workspace_binding_id: "binding-codex",
          model_id: "gpt-local",
          runtime_engine_id: "codex",
          binding_digest: "codex-digest",
        },
      }),
      activeThread: thread("free"),
      providers: [provider({ provider_id: "codex", label: "Codex", provider_role: "runtime_engine" })],
    });

    expect(selected?.provider_id).toBe("codex");
    expect(selected?.agentic_containment_status).toBeUndefined();
  });

  it("keeps an unavailable pinned Codex session in its native family", () => {
    const selected = selectedProviderForSession({
      activeProviderId: "hosted:openrouter:model-a",
      activeSession: session({
        runtime_mode: "agentic",
        provider_id: "codex",
        execution_binding: {
          workspace_binding_id: "binding-codex-unavailable",
          model_id: "gpt-pinned",
          runtime_engine_id: "codex",
          adapter_id: "codex-app-server",
          model_provider_id: "codex",
          provider_protocol: "codex-app-server-stdio",
          binding_digest: "codex-digest",
        },
      }),
      activeThread: thread("free"),
      providers: [provider({
        provider_id: "hosted:openrouter:model-a",
        label: "Hosted fallback",
        provider_role: "model_provider",
        kind: "hosted_api",
      })],
    });

    expect(selected).toMatchObject({
      provider_id: "pinned-session:binding-codex-unavailable",
      label: "gpt-pinned",
      execution_family: "native_agent",
      selectable: false,
      workspace_profile_binding_id: "binding-codex-unavailable",
    });
  });

  it("renders a contained fallback for a pinned remote profile removed from selection", () => {
    const selected = selectedProviderForSession({
      activeProviderId: "codex",
      activeSession: session({
        runtime_mode: "agentic",
        provider_id: "maverick-tool-loop",
        execution_binding: {
          workspace_binding_id: "binding-remote",
          model_provider_id: "openrouter",
          model_id: "deepseek/deepseek-v4-flash",
          runtime_engine_id: "maverick-tool-loop",
          binding_digest: "remote-digest",
        },
        agentic_containment: { status: "NO-GO", reason_code: "hosted_agent_runtime_disabled" },
        agentic_governance: {
          display_name: "OpenRouter DeepSeek V4 Flash · DeepInfra FP8 · fake-data preview",
          profile_definition_id: "profile-openrouter",
          profile_definition_revision: "12",
          workspace_binding_id: "binding-remote",
          workspace_binding_revision: 4,
          runtime_engine_id: "maverick-tool-loop",
          model_provider_id: "openrouter",
          model_id: "deepseek/deepseek-v4-flash",
          rollout_status: "suspended",
          containment: { status: "NO-GO", reason_code: "hosted_agent_runtime_disabled" },
          data_destination: {
            provider_id: "openrouter",
            endpoint_id: "openrouter-chat-completions-v1",
            upstream_provider_ids: ["deepinfra/fp8"],
            display_label: "openrouter → deepinfra/fp8 · openrouter-chat-completions-v1",
          },
          egress_policy: {
            policy_id: "remote-agentic-contained",
            revision: "2",
            allowed_remote_data_classes: ["public"],
          },
          data_policy: {
            collection: "deny",
            require_zdr: true,
            attestation_state: "not_attested",
            attestation: {
              state: "not_attested",
              authoritative: false,
              declaration: null,
              scope: null,
              revision: null,
              updated_at: null,
            },
          },
          certificate_posture: {
            certificate_id: "certificate-openrouter-12",
            effective_status: "revoked",
            eligibility: "ineligible",
            expires_at: "2026-09-30T00:00:00Z",
            pinned_evidence_digest: "evidence-digest",
          },
          effective_capabilities: {
            status: "blocked",
            reason_code: "hosted_agent_runtime_disabled",
            snapshot_digest: "blocked-capability-snapshot",
            capabilities: {
              streaming: false,
              tool_orchestration: false,
              cli: false,
              mcp: false,
              skill_catalog: false,
              filesystem_list: false,
              filesystem_read: false,
              filesystem_write: false,
              shell: false,
              interrupt: false,
              same_turn_steering: false,
              recovery: false,
              confirmation_resume: false,
              provider_private_state: false,
              attachment_modalities: [],
              app_references: false,
              confirmations: false,
            },
          },
        },
      }),
      activeThread: thread("free"),
      providers: [provider({ provider_id: "codex", label: "Codex", provider_role: "runtime_engine" })],
    });

    expect(selected?.provider_id).toBe("contained-session:binding-remote");
    expect(selected?.label).toBe("OpenRouter DeepSeek V4 Flash · DeepInfra FP8 · fake-data preview");
    expect(selected?.description).toBe("openrouter → deepinfra/fp8 · openrouter-chat-completions-v1");
    expect(selected?.agentic_containment_reason).toBe("hosted_agent_runtime_disabled");
    expect(selected?.agentic_certificate_status).toBe("revoked");
    expect(selected?.agentic_certificate_posture?.eligibility).toBe("ineligible");
    expect(selected?.agentic_egress_policy?.allowed_remote_data_classes).toEqual(["public"]);
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
