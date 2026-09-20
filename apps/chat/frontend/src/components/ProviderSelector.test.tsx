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
    provider_role: "runtime_engine",
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
    provider_id: "agentic:binding-google",
    label: "Gemini 3.6 Flash",
    description: "Google AI Studio",
    status: "active",
    provider_role: "runtime_engine",
    default_model_family: "gemini-3.6-flash",
    workspace_profile_binding_id: "binding-google",
    execution_family: "maverick_agent",
    selectable: true,
    provider_detail: "Provider: Google AI Studio · Destination: Google AI Studio API",
    profile_detail: "Runtime: maverick-tool-loop · google-ai-studio/gemini-3.6-flash",
    default_reasoning_effort: "high",
    supported_reasoning_efforts: [
      { effort: "high", label: "High", description: null },
    ],
  },
  {
    provider_id: "agentic:binding-openrouter",
    label: "GLM 5.3 Flash",
    description: "OpenRouter",
    status: "active",
    provider_role: "runtime_engine",
    default_model_family: "z-ai/glm-5.3-flash",
    workspace_profile_binding_id: "binding-openrouter",
    execution_family: "maverick_agent",
    selectable: true,
    provider_detail: "Provider: OpenRouter · Destination: OpenRouter via Relace",
    profile_detail: "Runtime: maverick-tool-loop · openrouter/z-ai/glm-5.3-flash",
    default_reasoning_effort: "high",
    supported_reasoning_efforts: [
      { effort: "max", label: "Maximum", description: null },
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
  providers = providerOptions,
  reasoningEffort = "",
}: {
  activeProviderId?: string;
  locked?: boolean;
  onSelect?: (providerId: string, reasoningEffort?: string) => void;
  onReasoningEffortChange?: (effort: string) => void;
  providers?: ProviderItem[];
  reasoningEffort?: string;
} = {}) {
  container = document.createElement("div");
  document.body.append(container);
  root = createRoot(container);

  await act(async () => {
    root?.render(
      <ProviderSelector
        activeProviderId={activeProviderId}
        disabled={false}
        locked={locked}
        onReasoningEffortChange={onReasoningEffortChange}
        onSelect={onSelect}
        providers={providers}
        reasoningEffort={reasoningEffort}
      />,
    );
  });

  if (!container) {
    throw new Error("Provider selector test container was not created");
  }
  return container;
}

function optionByText(element: Element, text: string): HTMLButtonElement {
  const option = Array.from(element.querySelectorAll<HTMLButtonElement>('[role="option"]')).find((button) =>
    button.textContent?.includes(text),
  );
  expect(option).toBeInstanceOf(HTMLButtonElement);
  return option as HTMLButtonElement;
}

async function openMenu(element: Element) {
  await act(async () => {
    element.querySelector<HTMLButtonElement>('[aria-label^="Model:"]')?.click();
  });
}

describe("ProviderSelector", () => {
  it("keeps the selected model and reasoning in the composer trigger", async () => {
    const element = await renderSelector();
    const trigger = element.querySelector<HTMLButtonElement>('[aria-label="Model: GPT-5.6-Sol · Max"]');

    expect(trigger).toBeInstanceOf(HTMLButtonElement);
    expect(trigger?.textContent).toContain("GPT-5.6-Sol");
    expect(trigger?.textContent).toContain("Max");
  });

  it("renders compact CLI and API sections with only model and reasoning", async () => {
    const element = await renderSelector();
    await openMenu(element);

    expect(element.querySelector('[aria-label="Search models"]')).toBeNull();
    expect(
      Array.from(element.querySelectorAll(".chatapp-provider-menu__family-heading span"))
        .map((node) => node.textContent),
    ).toEqual(["CLI models", "API models"]);
    expect(element.querySelectorAll('[role="option"]')).toHaveLength(3);
    expect(element.querySelectorAll(".chatapp-provider-menu__description")).toHaveLength(0);
    expect(element.querySelectorAll(".chatapp-provider-menu__meta")).toHaveLength(0);
    expect(element.textContent).not.toContain("Relace");
    expect(element.textContent).not.toContain("Google AI Studio");
    expect(element.textContent).not.toContain("maverick-tool-loop");
    expect(element.textContent).not.toContain("Text-only");
  });

  it("changes reasoning for the selected model", async () => {
    const onReasoningEffortChange = vi.fn();
    const element = await renderSelector({ onReasoningEffortChange });
    await openMenu(element);
    const reasoning = element.querySelector<HTMLSelectElement>('[aria-label="Reasoning for GPT-5.6-Sol"]');

    await act(async () => {
      if (!reasoning) return;
      reasoning.value = "xhigh";
      reasoning.dispatchEvent(new Event("change", { bubbles: true }));
    });

    expect(onReasoningEffortChange).toHaveBeenCalledWith("xhigh");
  });

  it("selects an API model together with its reasoning", async () => {
    const onSelect = vi.fn();
    const element = await renderSelector({ onSelect });
    await openMenu(element);
    const reasoning = element.querySelector<HTMLSelectElement>('[aria-label="Reasoning for GLM 5.3 Flash"]');

    await act(async () => {
      if (!reasoning) return;
      reasoning.value = "max";
      reasoning.dispatchEvent(new Event("change", { bubbles: true }));
    });

    expect(onSelect).toHaveBeenCalledWith("agentic:binding-openrouter", "max");
  });

  it("supports compact listbox keyboard selection without a search field", async () => {
    const onSelect = vi.fn();
    const element = await renderSelector({ onSelect });
    await openMenu(element);
    const menu = element.querySelector<HTMLDivElement>('[role="listbox"]');

    await act(async () => {
      menu?.dispatchEvent(new KeyboardEvent("keydown", { bubbles: true, key: "ArrowDown" }));
      menu?.dispatchEvent(new KeyboardEvent("keydown", { bubbles: true, key: "Enter" }));
    });

    expect(onSelect).toHaveBeenCalledWith("agentic:binding-google");
  });

  it("selects a model by clicking its row", async () => {
    const onSelect = vi.fn();
    const element = await renderSelector({ onSelect });
    await openMenu(element);

    await act(async () => {
      optionByText(element, "GLM 5.3 Flash").click();
    });

    expect(onSelect).toHaveBeenCalledWith("agentic:binding-openrouter");
    expect(element.querySelector('[role="listbox"]')).toBeNull();
  });

  it("does not show unavailable models", async () => {
    const element = await renderSelector({
      providers: [
        ...providerOptions,
        {
          ...providerOptions[1],
          provider_id: "agentic:incomplete",
          label: "Incomplete agent",
          selectable: false,
        },
      ],
    });
    await openMenu(element);

    expect(element.textContent).not.toContain("Incomplete agent");
  });

  it("does not open while locked to an existing runtime session", async () => {
    const element = await renderSelector({ locked: true });
    const trigger = element.querySelector<HTMLButtonElement>('[aria-label="Model: GPT-5.6-Sol · Max"]');

    expect(trigger?.disabled).toBe(true);
    expect(trigger?.title).toBe("GPT-5.6-Sol · Max. Start a new chat to change model or reasoning.");
    await act(async () => trigger?.click());
    expect(element.querySelector('[role="listbox"]')).toBeNull();
  });
});
