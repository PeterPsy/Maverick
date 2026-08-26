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
        attestation_state: "unavailable",
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
});
