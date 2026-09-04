/**
 * @vitest-environment happy-dom
 */
import { act } from "react";
import { createRoot } from "react-dom/client";
import type { Root } from "react-dom/client";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { ProviderItem } from "../api/client";
import { ProviderSelector } from "./ProviderSelector";

const providerOptions: ProviderItem[] = [
  {
    provider_id: "codex",
    label: "GPT-5.6-Sol",
    description: "Codex",
    status: "active",
    execution_family: "native_agent",
    selectable: true,
    default_model_family: null,
    default_reasoning_effort: "max",
    supported_reasoning_efforts: [
      { effort: "high", label: "High", description: null },
      { effort: "xhigh", label: "Extra high", description: null },
      { effort: "max", label: "Max", description: null },
    ],
  },
  {
    provider_id: "hosted:openrouter:google%2Fgemma-4-31b-it%3Afree",
    label: "Gemma 4 31B (free)",
    description: "OpenRouter",
    status: "active",
    default_model_family: "google/gemma-4-31b-it:free",
    hosted_provider_id: "openrouter",
    hosted_model_id: "google/gemma-4-31b-it:free",
    execution_family: "hosted_text",
    selectable: true,
    profile_detail: "No workspace tools or actions.",
  },
  {
    provider_id: "hosted:openrouter:nvidia%2Fnemotron-3-ultra-550b-a55b%3Afree",
    label: "Nemotron 3 Ultra (free)",
    description: "OpenRouter",
    status: "active",
    default_model_family: "nvidia/nemotron-3-ultra-550b-a55b:free",
    hosted_provider_id: "openrouter",
    hosted_model_id: "nvidia/nemotron-3-ultra-550b-a55b:free",
    execution_family: "hosted_text",
    selectable: true,
    profile_detail: "No workspace tools or actions.",
  },
  {
    provider_id: "agentic:binding-google",
    label: "Gemini 3.6 Flash",
    description: "Google AI Studio",
    status: "active",
    default_model_family: "gemini-3.6-flash",
    workspace_profile_binding_id: "binding-google",
    execution_family: "maverick_agent",
    selectable: true,
    provider_detail: "Provider: Google AI Studio · Destination: Google AI Studio API",
    profile_detail: "Profile: google@1 · Recipe: google@1 · Full Workspace: codex-baseline-v20",
    default_reasoning_effort: "high",
    supported_reasoning_efforts: [
      { effort: "minimal", label: "Minimal", description: null },
      { effort: "low", label: "Low", description: null },
      { effort: "medium", label: "Medium", description: null },
      { effort: "high", label: "High", description: null },
    ],
  },
  {
    provider_id: "agentic:binding-openrouter",
    label: "DeepSeek V4 Flash",
    description: "OpenRouter",
    status: "active",
    default_model_family: "deepseek/deepseek-v4-flash",
    workspace_profile_binding_id: "binding-openrouter",
    execution_family: "maverick_agent",
    selectable: true,
    provider_detail: "Provider: OpenRouter · Destination: OpenRouter via DeepInfra FP8",
    profile_detail: "Profile: openrouter@1 · Recipe: openrouter@1 · Full Workspace: codex-baseline-v20",
    default_reasoning_effort: "high",
    supported_reasoning_efforts: [
      { effort: "minimal", label: "Minimal", description: null },
      { effort: "low", label: "Low", description: null },
      { effort: "medium", label: "Medium", description: null },
      { effort: "high", label: "High", description: null },
    ],
  },
];

let root: Root | null = null;
let container: HTMLDivElement | null = null;

afterEach(() => {
  root?.unmount();
  root = null;
  container?.remove();
  container = null;
});

async function renderSelector({
  activeProviderId = "codex",
  locked = false,
  onSelect = () => undefined,
  onReasoningEffortChange = () => undefined,
  reasoningEffort = "",
}: {
  activeProviderId?: string;
  locked?: boolean;
  onSelect?: (providerId: string, reasoningEffort?: string) => void;
  onReasoningEffortChange?: (effort: string) => void;
  reasoningEffort?: string;
} = {}) {
  container = document.createElement("div");
  document.body.append(container);
  root = createRoot(container);

  await act(async () => {
    root?.render(
      <ProviderSelector activeProviderId={activeProviderId} disabled={false} locked={locked} onReasoningEffortChange={onReasoningEffortChange} onSelect={onSelect} providers={providerOptions} reasoningEffort={reasoningEffort} />,
    );
  });

  if (!container) {
    throw new Error("Provider selector test container was not created");
  }
  return container;
}

function changeInputValue(input: HTMLInputElement, value: string) {
  const valueSetter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")?.set;
  valueSetter?.call(input, value);
  input.dispatchEvent(new Event("input", { bubbles: true }));
  input.dispatchEvent(new Event("change", { bubbles: true }));
}

function optionByText(element: Element, text: string): HTMLButtonElement {
  const option = Array.from(element.querySelectorAll<HTMLButtonElement>('[role="option"]')).find((button) =>
    button.textContent?.includes(text),
  );
  expect(option).toBeInstanceOf(HTMLButtonElement);
  return option as HTMLButtonElement;
}

describe("ProviderSelector", () => {
  it("keeps the selected model reasoning control inside the model menu", async () => {
    const onReasoningEffortChange = vi.fn();
    const element = await renderSelector({ onReasoningEffortChange });

    await act(async () => {
      element.querySelector<HTMLButtonElement>('[aria-label="Model: GPT-5.6-Sol · Max"]')?.click();
    });
    const reasoning = element.querySelector<HTMLSelectElement>('[aria-label="Reasoning for GPT-5.6-Sol"]');
    expect(reasoning).toBeInstanceOf(HTMLSelectElement);
    expect(element.querySelector(".chatapp-reasoning-selector")).toBeNull();

    await act(async () => {
      if (!reasoning) return;
      reasoning.value = "xhigh";
      reasoning.dispatchEvent(new Event("change", { bubbles: true }));
    });
    expect(onReasoningEffortChange).toHaveBeenCalledWith("xhigh");
  });

  it("shows reasoning controls for Google and OpenRouter agentic models", async () => {
    const onSelect = vi.fn();
    const element = await renderSelector({ onSelect });

    await act(async () => {
      element.querySelector<HTMLButtonElement>('[aria-label="Model: GPT-5.6-Sol · Max"]')?.click();
    });

    expect(element.querySelector('[aria-label="Reasoning for Gemini 3.6 Flash"]')).toBeInstanceOf(HTMLSelectElement);
    const openRouterReasoning = element.querySelector<HTMLSelectElement>(
      '[aria-label="Reasoning for DeepSeek V4 Flash"]',
    );
    expect(openRouterReasoning).toBeInstanceOf(HTMLSelectElement);

    await act(async () => {
      if (!openRouterReasoning) return;
      openRouterReasoning.value = "high";
      openRouterReasoning.dispatchEvent(new Event("change", { bubbles: true }));
    });

    expect(onSelect).toHaveBeenCalledWith("agentic:binding-openrouter", "high");
  });

  it("opens a searchable model dropdown and keeps the selected model name visible", async () => {
    const onSelect = vi.fn();
    const element = await renderSelector({ onSelect });

    const trigger = element.querySelector<HTMLButtonElement>('[aria-label="Model: GPT-5.6-Sol · Max"]');
    expect(trigger).toBeInstanceOf(HTMLButtonElement);
    expect(trigger?.textContent).toContain("GPT-5.6-Sol");
    expect(trigger?.textContent).toContain("Max");
    expect(trigger?.textContent).not.toContain("expand_more");

    await act(async () => {
      trigger?.click();
    });

    const searchInput = element.querySelector<HTMLInputElement>('[aria-label="Search models"]');
    expect(searchInput).toBeInstanceOf(HTMLInputElement);
    expect(element.querySelector('[role="listbox"]')).toBeInstanceOf(HTMLDivElement);
    expect(element.querySelector(".chatapp-provider-menu__header")).toBeNull();
    expect(element.querySelector(".chatapp-provider-menu__search-label")).toBeNull();

    await act(async () => {
      changeInputValue(searchInput as HTMLInputElement, "nemotron");
    });

    expect(element.textContent).toContain("Nemotron 3 Ultra (free)");
    expect(element.textContent).not.toContain("Gemma 4 31B (free)");

    await act(async () => {
      optionByText(element, "Nemotron").click();
    });

    expect(onSelect).toHaveBeenCalledWith("hosted:openrouter:nvidia%2Fnemotron-3-ultra-550b-a55b%3Afree");
    expect(element.querySelector('[aria-label="Search models"]')).toBeNull();
  });

  it("selects the active filtered model with Enter", async () => {
    const onSelect = vi.fn();
    const element = await renderSelector({ onSelect });
    const trigger = element.querySelector<HTMLButtonElement>('[aria-label="Model: GPT-5.6-Sol · Max"]');

    await act(async () => {
      trigger?.click();
    });

    const searchInput = element.querySelector<HTMLInputElement>('[aria-label="Search models"]');
    expect(searchInput).toBeInstanceOf(HTMLInputElement);

    await act(async () => {
      changeInputValue(searchInput as HTMLInputElement, "gemma");
      searchInput?.dispatchEvent(new KeyboardEvent("keydown", { bubbles: true, cancelable: true, key: "Enter" }));
    });

    expect(onSelect).toHaveBeenCalledWith("hosted:openrouter:google%2Fgemma-4-31b-it%3Afree");
  });

  it("does not open or select while locked to an existing runtime session", async () => {
    const onSelect = vi.fn();
    const element = await renderSelector({ locked: true, onSelect });

    const trigger = element.querySelector<HTMLButtonElement>('[aria-label="Model: GPT-5.6-Sol · Max"]');
    expect(trigger).toBeInstanceOf(HTMLButtonElement);
    expect(trigger?.disabled).toBe(true);
    expect(trigger?.title).toBe("GPT-5.6-Sol · Max. Start a new chat to change model or reasoning.");

    await act(async () => {
      trigger?.click();
    });

    expect(element.querySelector('[role="listbox"]')).toBeNull();
    expect(onSelect).not.toHaveBeenCalled();
  });

  it("shows the normative families and pinned provider/profile details", async () => {
    const element = await renderSelector();

    await act(async () => {
      element.querySelector<HTMLButtonElement>('[aria-label="Model: GPT-5.6-Sol · Max"]')?.click();
    });

    const googleOption = optionByText(element, "Gemini 3.6 Flash");
    const row = googleOption.closest(".chatapp-provider-menu__option-block");
    expect(row?.querySelector(".chatapp-provider-menu__name")?.textContent).toBe("Gemini 3.6 Flash");
    expect(row?.querySelector(".chatapp-provider-menu__description")?.textContent).toBe("Google AI Studio");
    expect(row?.querySelector('[aria-label="Reasoning for Gemini 3.6 Flash"]')).toBeInstanceOf(HTMLSelectElement);
    const familyLabels = Array.from(element.querySelectorAll(".chatapp-provider-menu__family-heading strong"))
      .map((node) => node.textContent);
    expect(familyLabels).toEqual([
      "Native Agents (CLI)",
      "Maverick Agents (API)",
      "Text-only Models (API)",
    ]);
    const familyDescriptions = Array.from(element.querySelectorAll(".chatapp-provider-menu__family-heading span"))
      .map((node) => node.textContent);
    expect(familyDescriptions).toEqual([
      "External coding-agent runtimes such as Codex, Claude Code, and Gemini CLI. They use their own agent loop and tools, while Maverick launches, connects to, and supervises them.",
      "API models made agentic by Maverick. Maverick provides workspace context, tools, the execution loop, approvals, finalization, and recovery.",
      "API models without workspace tools or an action loop. They generate text from the context provided by Maverick but cannot perform workspace actions.",
    ]);
    expect(googleOption.textContent).toContain("Destination: Google AI Studio API");
    expect(googleOption.textContent).toContain("Full Workspace: codex-baseline-v20");
    expect(element.textContent).toContain("No workspace tools or actions.");
  });

  it("does not select an unavailable incomplete agent", async () => {
    const onSelect = vi.fn();
    const unavailable = {
      ...providerOptions[3],
      provider_id: "agentic:incomplete",
      label: "Incomplete agent",
      selectable: false,
      unavailable_reason: "full_workspace_policy_incomplete",
    };
    const element = await renderSelector({ onSelect });

    await act(async () => {
      root?.render(
        <ProviderSelector activeProviderId="codex" disabled={false} onSelect={onSelect} providers={[...providerOptions, unavailable]} />,
      );
    });
    await act(async () => {
      element.querySelector<HTMLButtonElement>('[aria-label^="Model:"]')?.click();
    });
    const option = optionByText(element, "Incomplete agent");
    expect(option.disabled).toBe(true);
    await act(async () => option.click());
    expect(onSelect).not.toHaveBeenCalledWith("agentic:incomplete");
  });
});
