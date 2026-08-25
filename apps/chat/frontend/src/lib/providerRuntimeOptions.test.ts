import { describe, expect, it } from "vitest";
import type { ProviderPayload } from "../api/client";
import { hostedProviderRuntimeConfig, providerItemsFromPayload } from "./providerRuntimeOptions";

const payload: ProviderPayload = {
  workspace_id: "default",
  active_provider: {
    provider_id: "codex",
    label: "Codex",
    description: "Agentic runtime",
    kind: "runtime_backend",
    provider_role: "runtime_engine",
    status: "active",
    default_model_family: "gpt-5.5",
  },
  hosted_text: {
    profile: "fast_model",
    active_provider: {
      provider_id: "openrouter",
      label: "OpenRouter",
      description: "Hosted text",
      kind: "hosted_api",
      provider_role: "model_provider",
      status: "active",
      default_model_family: "google/gemma-4-31b-it:free",
      model_options: [
        {
          model_id: "google/gemma-4-31b-it:free",
          label: "Gemma 4 31B (free)",
          description: null,
          default_reasoning_effort: null,
          supported_reasoning_efforts: [],
          input_modalities: ["text", "image"],
          output_modalities: ["text"],
        },
        {
          model_id: "nvidia/nemotron-3-ultra-550b-a55b:free",
          label: "Nemotron 3 Ultra (free)",
          description: null,
          default_reasoning_effort: null,
          supported_reasoning_efforts: [],
          input_modalities: ["text"],
          output_modalities: ["text"],
        },
        {
          model_id: "hexgrad/kokoro-82m",
          label: "Kokoro 82M",
          description: null,
          default_reasoning_effort: null,
          supported_reasoning_efforts: [],
          input_modalities: ["text"],
          output_modalities: ["speech"],
        },
      ],
    },
    selection: null,
    model_settings: {
      selected_model_id: "google/gemma-4-31b-it:free",
      selected_reasoning_effort: null,
      available_models: [
        {
          model_id: "google/gemma-4-31b-it:free",
          label: "Gemma 4 31B (free)",
          description: null,
          default_reasoning_effort: null,
          supported_reasoning_efforts: [],
          input_modalities: ["text", "image"],
          output_modalities: ["text"],
        },
        {
          model_id: "nvidia/nemotron-3-ultra-550b-a55b:free",
          label: "Nemotron 3 Ultra (free)",
          description: null,
          default_reasoning_effort: null,
          supported_reasoning_efforts: [],
          input_modalities: ["text"],
          output_modalities: ["text"],
        },
        {
          model_id: "hexgrad/kokoro-82m",
          label: "Kokoro 82M",
          description: null,
          default_reasoning_effort: null,
          supported_reasoning_efforts: [],
          input_modalities: ["text"],
          output_modalities: ["speech"],
        },
      ],
    },
    available_providers: [],
  },
};

const googleProvider = {
  provider_id: "google-ai-studio",
  label: "Google AI Studio",
  description: "Hosted Gemini text generation provider metadata.",
  kind: "hosted_api",
  provider_role: "model_provider",
  status: "active",
  default_model_family: "gemini-3.5-flash",
  model_options: [
    {
      model_id: "gemini-3.5-flash",
      label: "Gemini 3.5 Flash",
      description: null,
      default_reasoning_effort: null,
      supported_reasoning_efforts: [],
      input_modalities: ["text", "image"],
      output_modalities: ["text"],
    },
    {
      model_id: "gemini-3.1-flash-lite",
      label: "Gemini 3.1 Flash-Lite",
      description: null,
      default_reasoning_effort: null,
      supported_reasoning_efforts: [],
      input_modalities: ["text", "image"],
      output_modalities: ["text"],
    },
  ],
};

describe("provider runtime options", () => {
  it("maps agentic profiles to per-session choices without changing the runtime engine id", () => {
    const providers = providerItemsFromPayload({
      ...payload,
      agentic_profiles: {
        default_binding_id: "binding-codex",
        items: [
          {
            workspace_profile_binding_id: "binding-codex",
            definition_id: "profile-codex",
            definition_revision: "1",
            display_name: "Codex · gpt-5.6-sol · fake-data preview",
            runtime_engine_id: "codex",
            model_provider_id: "codex",
            model_id: "gpt-5.6-sol",
            default_reasoning_effort: "xhigh",
            supported_reasoning_efforts: [
              { effort: "high", label: "High", description: null },
              { effort: "xhigh", label: "Extra high", description: null },
            ],
            rollout_status: "available",
            enabled: true,
            is_default: true,
            selectable: true,
            containment_status: "GO",
            certified: true,
            certificate: {
              effective_status: "active",
              expires_at: "2026-09-16T00:00:00Z",
            },
            egress_policy_id: "fake-data-remote-preview",
            allowed_tool_handles: ["mcp:storage_read"],
            max_estimated_cost_microusd: 250_000,
          },
        ],
      },
    });

    expect(providers[0]).toMatchObject({
      provider_id: "codex",
      workspace_profile_binding_id: "binding-codex",
      default_model_family: "gpt-5.6-sol",
      label: "gpt-5.6-sol",
      description: "Codex",
      agentic_certificate_status: "active",
      agentic_egress_policy_id: "fake-data-remote-preview",
      agentic_allowed_tool_handles: ["mcp:storage_read"],
      agentic_max_estimated_cost_microusd: 250_000,
      agentic_containment_status: "GO",
      agentic_rollout_status: "available",
      default_reasoning_effort: "xhigh",
      supported_reasoning_efforts: [
        { effort: "high", label: "High", description: null },
        { effort: "xhigh", label: "Extra high", description: null },
      ],
    });
  });

  it("uses the model as title and provider as subtitle", () => {
    expect(providerItemsFromPayload(payload).map((provider) => ({
      title: provider.label,
      subtitle: provider.description,
    }))).toEqual([
      { title: "Codex", subtitle: "Agentic runtime" },
      { title: "Gemma 4 31B (free)", subtitle: "OpenRouter" },
      { title: "Nemotron 3 Ultra (free)", subtitle: "OpenRouter" },
    ]);
  });

  it("does not expose speech-only OpenRouter models as plain hosted chat choices", () => {
    expect(providerItemsFromPayload(payload).map((provider) => provider.hosted_model_id)).not.toContain("hexgrad/kokoro-82m");
  });

  it("maps hosted text provider choices to plain hosted chat runtime config", () => {
    const openRouter = providerItemsFromPayload(payload).find((provider) => provider.hosted_model_id === "google/gemma-4-31b-it:free");

    expect(hostedProviderRuntimeConfig(openRouter)).toMatchObject({
      agent_id: "chat",
      runtime_mode: "plain_hosted_chat",
      routing_profile: "fast_model",
      hosted_provider_id: "openrouter",
      hosted_model_id: "google/gemma-4-31b-it:free",
      skill_ids: [],
      source_app_id: "chat",
    });
  });

  it("keeps the selected hosted model id for non-default hosted choices", () => {
    const nemotron = providerItemsFromPayload(payload).find((provider) => provider.hosted_model_id === "nvidia/nemotron-3-ultra-550b-a55b:free");

    expect(hostedProviderRuntimeConfig(nemotron)).toMatchObject({
      hosted_provider_id: "openrouter",
      hosted_model_id: "nvidia/nemotron-3-ultra-550b-a55b:free",
      runtime_mode: "plain_hosted_chat",
    });
  });

  it("exposes active hosted models from available hosted providers", () => {
    const providers = providerItemsFromPayload({
      ...payload,
      hosted_text: {
        ...payload.hosted_text!,
        available_providers: [payload.hosted_text!.active_provider!, googleProvider],
      },
    });

    expect(providers.map((provider) => provider.label)).toContain("Gemini 3.5 Flash");
    expect(providers.map((provider) => provider.label)).toContain("Gemini 3.1 Flash-Lite");
    expect(providers.find((provider) => provider.hosted_model_id === "gemini-3.5-flash")?.description).toBe("Google AI Studio");
    expect(hostedProviderRuntimeConfig(providers.find((provider) => provider.hosted_model_id === "gemini-3.5-flash"))).toMatchObject({
      hosted_provider_id: "google-ai-studio",
      hosted_model_id: "gemini-3.5-flash",
      runtime_mode: "plain_hosted_chat",
    });
  });

  it("does not apply active Google model settings to an OpenRouter persisted selection", () => {
    const providers = providerItemsFromPayload({
      ...payload,
      hosted_text: {
        ...payload.hosted_text!,
        active_provider: googleProvider,
        selection: {
          workspace_id: "default",
          profile: "fast_model",
          provider_id: "openrouter",
          selection_reason: "configured by hosted model settings",
          updated_at: "2026-06-26T00:00:00Z",
          model_id: "hexgrad/kokoro-82m",
        },
        model_settings: {
          selected_model_id: "gemini-3.5-flash",
          selected_reasoning_effort: null,
          available_models: googleProvider.model_options!,
        },
        available_providers: [payload.hosted_text!.active_provider!, googleProvider],
      },
    });

    const labels = providers.map((provider) => provider.label);
    expect(labels).toContain("Gemini 3.5 Flash");
    expect(labels).toContain("Gemini 3.1 Flash-Lite");
    expect(labels).toContain("Gemma 4 31B (free)");
    expect(labels).toContain("Nemotron 3 Ultra (free)");
    expect(providers.find((provider) => provider.hosted_model_id === "gemini-3.5-flash")?.description).toBe("Google AI Studio");
    expect(providers.find((provider) => provider.hosted_model_id === "google/gemma-4-31b-it:free")?.description).toBe("OpenRouter");
  });
});
