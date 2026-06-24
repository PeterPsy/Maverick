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
        },
      ],
    },
    available_providers: [],
  },
};

describe("provider runtime options", () => {
  it("labels hosted text options with the selected model and provider", () => {
    expect(providerItemsFromPayload(payload).map((provider) => provider.label)).toEqual([
      "Codex",
      "Gemma 4 31B (free) - OpenRouter",
    ]);
  });

  it("maps hosted text provider choices to plain hosted chat runtime config", () => {
    const openRouter = providerItemsFromPayload(payload).find((provider) => provider.provider_id === "openrouter");

    expect(hostedProviderRuntimeConfig(openRouter)).toMatchObject({
      agent_id: "chat",
      runtime_mode: "plain_hosted_chat",
      routing_profile: "fast_model",
      skill_ids: [],
      source_app_id: "chat",
    });
  });
});
