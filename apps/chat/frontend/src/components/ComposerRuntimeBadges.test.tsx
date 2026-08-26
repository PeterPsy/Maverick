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
      label: "OpenRouter DeepSeek V4 Flash · DeepInfra FP8 · fake-data preview",
      description: "openrouter → deepinfra/fp8 · openrouter-chat-completions-v1",
      provider_role: "runtime_engine",
      status: "contained",
      default_model_family: "deepseek/deepseek-v4-flash",
      workspace_profile_binding_id: "binding-openrouter",
      agentic_containment_status: "NO-GO",
      agentic_containment_reason: "remote_agentic_attestation_unavailable",
      agentic_certificate_status: "revoked",
      agentic_data_destination: {
        provider_id: "openrouter",
        endpoint_id: "openrouter-chat-completions-v1",
        upstream_provider_ids: ["deepinfra/fp8"],
        display_label: "openrouter → deepinfra/fp8 · openrouter-chat-completions-v1",
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
      agentic_certificate_posture: {
        certificate_id: "certificate-openrouter-12",
        effective_status: "revoked",
        eligibility: "ineligible",
        expires_at: "2026-09-30T00:00:00Z",
        pinned_evidence_digest: "evidence-digest",
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
      '[aria-label^="Model: OpenRouter DeepSeek V4 Flash"]',
    );
    expect(selector).toBeInstanceOf(HTMLButtonElement);
    expect(selector?.disabled).toBe(true);
    expect(selector?.textContent).toContain("fake-data preview");
    const governance = container.querySelector<HTMLElement>(
      '[aria-label^="NO-GO agentic profile"]',
    );
    expect(governance?.textContent).toContain("NO-GO");
    expect(governance?.textContent).toContain("openrouter → deepinfra/fp8");
    expect(governance?.title).toContain("remote-agentic-contained@2");
    expect(governance?.title).toContain("data collection deny · ZDR required");
    expect(governance?.title).toContain("certificate revoked");
    expect(governance?.title).toContain("certificate eligibility ineligible");
    expect(onSelectProvider).not.toHaveBeenCalled();
  });

  it("uses the server-owned effective snapshot instead of overstating full access", async () => {
    const provider: ProviderItem = {
      provider_id: "session:binding-google",
      label: "Google agentic",
      description: "Certified fixture profile",
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
        certificate: {
          certificate_id: "certificate-google-1",
          suite_id: "google-agentic-certification",
          suite_version: "9",
          expires_at: "2026-09-30T00:00:00Z",
        },
        tcb: { posture: "active" },
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
    const governance = container.querySelector<HTMLElement>(".chatapp-agentic-profile-chip");
    expect(governance?.title).toContain("snapshot effective-snapshot-digest");
    expect(governance?.title).toContain("filesystem read yes / write no");
    expect(governance?.title).toContain("suite google-agentic-certification@9");
    expect(governance?.title).toContain("TCB active");
  });
});
