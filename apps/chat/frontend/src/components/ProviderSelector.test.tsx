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
    label: "Codex",
    description: "Agentic runtime",
    status: "active",
    default_model_family: null,
  },
  {
    provider_id: "hosted:openrouter:google%2Fgemma-4-31b-it%3Afree",
    label: "Gemma 4 31B (free) - OpenRouter",
    description: "Fast hosted model",
    status: "active",
    default_model_family: "google/gemma-4-31b-it:free",
    hosted_provider_id: "openrouter",
    hosted_model_id: "google/gemma-4-31b-it:free",
  },
  {
    provider_id: "hosted:openrouter:nvidia%2Fnemotron-3-ultra-550b-a55b%3Afree",
    label: "Nemotron 3 Ultra (free) - OpenRouter",
    description: "Large hosted model",
    status: "active",
    default_model_family: "nvidia/nemotron-3-ultra-550b-a55b:free",
    hosted_provider_id: "openrouter",
    hosted_model_id: "nvidia/nemotron-3-ultra-550b-a55b:free",
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
  onSelect = () => undefined,
}: {
  activeProviderId?: string;
  onSelect?: (providerId: string) => void;
} = {}) {
  container = document.createElement("div");
  document.body.append(container);
  root = createRoot(container);

  await act(async () => {
    root?.render(
      <ProviderSelector activeProviderId={activeProviderId} disabled={false} onSelect={onSelect} providers={providerOptions} />,
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
  it("opens a searchable model dropdown and keeps the selected model name visible", async () => {
    const onSelect = vi.fn();
    const element = await renderSelector({ onSelect });

    const trigger = element.querySelector<HTMLButtonElement>('[aria-label="Model: Codex"]');
    expect(trigger).toBeInstanceOf(HTMLButtonElement);
    expect(trigger?.textContent).toContain("Codex");
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

    expect(element.textContent).toContain("Nemotron 3 Ultra (free) - OpenRouter");
    expect(element.textContent).not.toContain("Gemma 4 31B (free) - OpenRouter");

    await act(async () => {
      optionByText(element, "Nemotron").click();
    });

    expect(onSelect).toHaveBeenCalledWith("hosted:openrouter:nvidia%2Fnemotron-3-ultra-550b-a55b%3Afree");
    expect(element.querySelector('[aria-label="Search models"]')).toBeNull();
  });

  it("selects the active filtered model with Enter", async () => {
    const onSelect = vi.fn();
    const element = await renderSelector({ onSelect });
    const trigger = element.querySelector<HTMLButtonElement>('[aria-label="Model: Codex"]');

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
});
