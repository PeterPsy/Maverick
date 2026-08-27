import { describe, expect, it } from "vitest";
import type { ChatThread, ProviderItem, RuntimeSession } from "../api/client";
import { composerRuntimeCapabilities } from "./composerRuntimeCapabilities";

function provider(overrides: Partial<ProviderItem> = {}): ProviderItem {
  return {
    provider_id: "codex",
    label: "Codex",
    description: "Local Codex runtime",
    provider_role: "runtime_engine",
    status: "active",
    default_model_family: "gpt-5.6-sol",
    ...overrides,
  };
}

function thread(overrides: Partial<ChatThread> = {}): ChatThread {
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
    availability: "free",
    created_at: "2026-08-27T07:00:00Z",
    updated_at: "2026-08-27T07:00:00Z",
    ...overrides,
  };
}

function session(overrides: Partial<RuntimeSession> = {}): RuntimeSession {
  return {
    session_id: "session-1",
    workspace_id: "default",
    agent_id: "chat",
    status: "running",
    effective_mode: "sandbox",
    runtime_mode: "agentic",
    provider_id: "codex",
    ...overrides,
  };
}

describe("composerRuntimeCapabilities", () => {
  it("retains local Codex references and attachments during capability-projection rollout skew", () => {
    for (const context of [
      { activeSession: null, activeThread: null },
      {
        activeSession: session({
          execution_binding: exactCodexBinding(),
        }),
        activeThread: thread({ provider_id: "codex", runtime_mode: "agentic" }),
      },
    ]) {
      expect(composerRuntimeCapabilities({
        ...context,
        selectedProvider: provider(),
      })).toEqual({
        allowedAttachmentInputModalities: null,
        appReferencesAllowed: true,
      });
    }
  });

  it("does not mistake a remote session's Codex display fallback for local authority", () => {
    expect(composerRuntimeCapabilities({
      activeSession: session({
        provider_id: "maverick-tool-loop",
        execution_binding: {
          workspace_binding_id: "binding-remote",
          runtime_engine_id: "maverick-tool-loop",
          model_id: "remote-model",
          binding_digest: "remote-binding",
        },
      }),
      activeThread: thread({ provider_id: "maverick-tool-loop" }),
      selectedProvider: provider(),
    })).toEqual({
      allowedAttachmentInputModalities: [],
      appReferencesAllowed: false,
    });
  });

  it("does not apply the Codex rollout fallback to ambiguous or contained sessions", () => {
    const ambiguousBoundSession = {
      activeSession: session({
        execution_binding: {
          workspace_binding_id: "binding-ambiguous",
          runtime_engine_id: "codex",
          model_id: "remote-model",
          binding_digest: "ambiguous-codex",
        },
      }),
      activeThread: thread({ provider_id: "codex" }),
      selectedProvider: provider(),
    };
    const containedSession = {
      activeSession: session(),
      activeThread: thread({ provider_id: "codex" }),
      selectedProvider: provider({
        status: "contained",
        agentic_containment_status: "NO-GO",
        agentic_effective_capabilities: effectiveCapabilities({
          attachment_modalities: ["file"],
          app_references: true,
        }),
      }),
    };

    for (const context of [ambiguousBoundSession, containedSession]) {
      expect(composerRuntimeCapabilities(context)).toEqual({
        allowedAttachmentInputModalities: [],
        appReferencesAllowed: false,
      });
    }
  });

  it("uses an active server snapshot for governed agentic composer features", () => {
    expect(composerRuntimeCapabilities({
      activeSession: null,
      activeThread: null,
      selectedProvider: provider({
        agentic_effective_capabilities: effectiveCapabilities({
          attachment_modalities: ["image", "file"],
          app_references: true,
        }),
      }),
    })).toEqual({
      allowedAttachmentInputModalities: ["image", "file"],
      appReferencesAllowed: true,
    });
  });

  it("fails closed for blocked or missing remote capability snapshots", () => {
    const remote = provider({ provider_id: "maverick-tool-loop" });
    const blocked = provider({
      provider_id: "maverick-tool-loop",
      agentic_effective_capabilities: effectiveCapabilities({
        attachment_modalities: ["file"],
        app_references: true,
      }, "blocked"),
    });

    for (const selectedProvider of [remote, blocked]) {
      expect(composerRuntimeCapabilities({
        activeSession: null,
        activeThread: null,
        selectedProvider,
      })).toEqual({
        allowedAttachmentInputModalities: [],
        appReferencesAllowed: false,
      });
    }
  });

  it("keeps plain-hosted attachment modalities and rejects operative references", () => {
    const selectedProvider = provider({
      provider_id: "hosted:openrouter:model-a",
      provider_role: "model_provider",
      kind: "hosted_api",
      input_modalities: ["text", "image"],
    });

    for (const activeThread of [
      null,
      thread({
        provider_id: "openrouter",
        runtime_mode: "plain_hosted_chat",
      }),
    ]) {
      expect(composerRuntimeCapabilities({
        activeSession: null,
        activeThread,
        selectedProvider,
      })).toEqual({
        allowedAttachmentInputModalities: ["text", "image"],
        appReferencesAllowed: false,
      });
    }
  });
});

function exactCodexBinding(): NonNullable<RuntimeSession["execution_binding"]> {
  return {
    workspace_binding_id: "workspace-agentic-default",
    runtime_engine_id: "codex",
    adapter_id: "codex-app-server",
    model_provider_id: "codex",
    provider_protocol: "codex-app-server-stdio",
    model_id: "gpt-5.6-sol",
    binding_digest: "exact-codex-binding",
  };
}

function effectiveCapabilities(
  capabilities: { attachment_modalities: string[]; app_references: boolean },
  status: "active" | "blocked" = "active",
): NonNullable<ProviderItem["agentic_effective_capabilities"]> {
  return {
    status,
    reason_code: status === "active" ? null : "runtime_authority_unavailable",
    snapshot_digest: `${status}-snapshot`,
    capabilities: {
      streaming: status === "active",
      tool_orchestration: status === "active",
      cli: status === "active",
      mcp: status === "active",
      skill_catalog: status === "active",
      filesystem_list: false,
      filesystem_read: status === "active",
      filesystem_write: status === "active",
      shell: status === "active",
      interrupt: status === "active",
      same_turn_steering: status === "active",
      recovery: status === "active",
      confirmation_resume: false,
      provider_private_state: false,
      confirmations: false,
      ...capabilities,
    },
  };
}
