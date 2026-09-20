/**
 * @vitest-environment happy-dom
 */
import { act } from "react";
import { createRoot } from "react-dom/client";
import type { Root } from "react-dom/client";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { ProviderItem } from "../api/client";
import { ComposerRuntimeBadges } from "./ComposerRuntimeBadges";

let root: Root | null = null;
let container: HTMLDivElement | null = null;

afterEach(() => {
  root?.unmount();
  root = null;
  container?.remove();
  container = null;
});

describe("ComposerRuntimeBadges contained profile governance", () => {
  it("shows the authoritative label, NO-GO destination, and keeps the profile locked", async () => {
    const onSelectProvider = vi.fn();
    const provider: ProviderItem = {
      provider_id: "contained-session:binding-openrouter",
      label: "OpenRouter GLM 5.3 Flash · Relace FP4 · fake-data preview",
      description: "openrouter → relace/fp4 · openrouter-chat-completions-v1",
      provider_role: "runtime_engine",
      status: "contained",
      default_model_family: "z-ai/glm-5.3-flash",
      workspace_profile_binding_id: "binding-openrouter",
      agentic_containment_status: "NO-GO",
      agentic_containment_reason: "remote_agentic_attestation_unavailable",
      agentic_data_destination: {
        provider_id: "openrouter",
        endpoint_id: "openrouter-chat-completions-v1",
        upstream_provider_ids: ["relace/fp4"],
        display_label: "openrouter → relace/fp4 · openrouter-chat-completions-v1",
      },
      agentic_egress_policy: {
        policy_id: "remote-agentic-contained",
        revision: "2",
        allowed_remote_data_classes: ["public"],
      },
      agentic_data_policy: {
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
    };
    container = document.createElement("div");
    document.body.append(container);
    root = createRoot(container);

    await act(async () => {
      root?.render(
        <ComposerRuntimeBadges
          activeProviderId={provider.provider_id}
          disabled={false}
          executionMode="sandbox"
          locked
          onReasoningEffortChange={() => undefined}
          onSelectProvider={onSelectProvider}
          providers={[provider]}
        />,
      );
    });

    const selector = container.querySelector<HTMLButtonElement>(
      '[aria-label^="Model: OpenRouter GLM 5.3 Flash"]',
    );
    expect(selector).toBeInstanceOf(HTMLButtonElement);
    expect(selector?.disabled).toBe(true);
    expect(selector?.textContent).toContain("fake-data preview");
    const governance = container.querySelector<HTMLElement>(
      '[aria-label^="NO-GO agentic profile"]',
    );
    expect(governance?.textContent).toContain("NO-GO");
    expect(governance?.textContent).toContain("openrouter → relace/fp4");
    expect(governance?.title).toContain("remote-agentic-contained@2");
    expect(governance?.title).toContain("data collection deny · ZDR required");
    expect(governance?.title).toContain("destination openrouter → relace/fp4");
    expect(onSelectProvider).not.toHaveBeenCalled();
  });

  it("uses the server-owned effective snapshot instead of overstating full access", async () => {
    const provider: ProviderItem = {
      provider_id: "session:binding-google",
      label: "Google agentic",
      description: "Runtime profile fixture",
      status: "available",
      default_model_family: "gemini",
      workspace_profile_binding_id: "binding-google",
      agentic_containment_status: "GO",
      agentic_data_destination: {
        provider_id: "google-ai-studio",
        endpoint_id: "interactions-v1",
        upstream_provider_ids: ["google-ai-studio"],
        display_label: "Google AI Studio",
      },
      agentic_effective_capabilities: {
        status: "active",
        reason_code: null,
        snapshot_digest: "effective-snapshot-digest",
        execution_mode: "full-access",
        capabilities: {
          streaming: true,
          tool_orchestration: true,
          cli: false,
          mcp: false,
          skill_catalog: true,
          filesystem_list: true,
          filesystem_read: true,
          filesystem_write: false,
          shell: false,
          interrupt: true,
          same_turn_steering: false,
          recovery: false,
          confirmation_resume: true,
          provider_private_state: true,
          attachment_modalities: ["text"],
          app_references: false,
          confirmations: true,
        },
        provider: {
          provider_id: "google-ai-studio",
          effective_upstream_ids: ["google-ai-studio"],
          health_status: "healthy",
        },
        data_policy: {
          allowed_remote_data_classes: ["public"],
          collection: "deny",
          require_zdr: true,
        },
      },
    };
    container = document.createElement("div");
    document.body.append(container);
    root = createRoot(container);

    await act(async () => {
      root?.render(
        <ComposerRuntimeBadges
          activeProviderId={provider.provider_id}
          disabled={false}
          executionMode="full-access"
          onReasoningEffortChange={() => undefined}
          onSelectProvider={() => undefined}
          providers={[provider]}
        />,
      );
    });

    expect(container.querySelector('[aria-label="Full access runtime"]')).toBeNull();
    expect(container.querySelector('[aria-label="Policy-limited runtime"]')).not.toBeNull();
    expect(container.querySelector(".chatapp-agentic-profile-chip")).toBeNull();
  });

  it("shows full access for an active native CLI authority", async () => {
    const provider: ProviderItem = {
      provider_id: "session:binding-antigravity",
      label: "Gemini 3.8 Flash",
      description: "Antigravity CLI",
      status: "available",
      default_model_family: "gemini-3.8-flash-high",
      workspace_profile_binding_id: "binding-antigravity",
      agentic_containment_status: "GO",
      agentic_effective_capabilities: {
        status: "active",
        reason_code: null,
        snapshot_digest: "antigravity-effective-snapshot",
        execution_mode: "full-access",
        capabilities: {
          streaming: true,
          tool_orchestration: true,
          cli: true,
          mcp: true,
          skill_catalog: true,
          filesystem_list: true,
          filesystem_read: true,
          filesystem_write: true,
          shell: true,
          interrupt: true,
          same_turn_steering: true,
          recovery: true,
          confirmation_resume: true,
          provider_private_state: true,
          attachment_modalities: ["text", "image"],
          app_references: true,
          confirmations: true,
        },
        provider: {
          provider_id: "google",
          effective_upstream_ids: ["google"],
          health_status: "healthy",
        },
        data_policy: {
          allowed_remote_data_classes: ["public"],
          collection: "deny",
          require_zdr: false,
        },
      },
    };
    container = document.createElement("div");
    document.body.append(container);
    root = createRoot(container);

    await act(async () => {
      root?.render(
        <ComposerRuntimeBadges
          activeProviderId={provider.provider_id}
          disabled={false}
          executionMode="full-access"
          onReasoningEffortChange={() => undefined}
          onSelectProvider={() => undefined}
          providers={[provider]}
        />,
      );
    });

    expect(container.querySelector('[aria-label="Full access runtime"]')).not.toBeNull();
    expect(container.querySelector('[aria-label="Policy-limited runtime"]')).toBeNull();
  });
});
