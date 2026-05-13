/**
 * @vitest-environment happy-dom
 */
import { act, useState } from "react";
import { createRoot } from "react-dom/client";
import type { Root } from "react-dom/client";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { AppReference, ProviderItem } from "../api/client";
import type { MentionItem } from "../lib/mentions";
import { ChatComposer } from "./ChatComposer";

const providers: ProviderItem[] = [
  {
    provider_id: "codex",
    label: "Codex",
    description: "",
    status: "configured",
    default_model_family: null,
  },
];

const checklistReference: AppReference = {
  type: "entity",
  app_id: "checklist",
  entity_type: "checklist",
  entity_id: "check_6f4e74d9f31d",
  label: "Link checklist nella chat con @",
  summary: "Checklist operativa",
  deep_link: "/app/checklist/checklists/check_6f4e74d9f31d",
};

const checklistMention: MentionItem = {
  id: "entity:checklist:checklist:check_6f4e74d9f31d",
  label: checklistReference.label,
  description: "checklist · checklist · Checklist operativa",
  kind: "entity",
  reference: checklistReference,
};

let root: Root | null = null;
let container: HTMLDivElement | null = null;

afterEach(() => {
  root?.unmount();
  root = null;
  container?.remove();
  container = null;
  vi.useRealTimers();
});

async function renderComposer({
  onReferenceAdd = () => undefined,
  onSearchReferences = async () => [],
}: {
  onReferenceAdd?: (reference: AppReference) => void;
  onSearchReferences?: (query: string, signal: AbortSignal) => Promise<MentionItem[]>;
} = {}) {
  container = document.createElement("div");
  document.body.append(container);
  root = createRoot(container);
  let latestValue = "";

  function Harness() {
    const [value, setValue] = useState("");
    latestValue = value;
    return (
      <ChatComposer
        activeProviderId="codex"
        attachments={[]}
        canStopTurn={false}
        disabled={false}
        error={null}
        executionMode={null}
        isSending={false}
        mentionItems={[]}
        onAddAttachments={() => undefined}
        onChange={(nextValue) => {
          latestValue = nextValue;
          setValue(nextValue);
        }}
        onReferenceAdd={onReferenceAdd}
        onSearchReferences={onSearchReferences}
        onSelectProvider={() => undefined}
        onRemoveAttachment={() => undefined}
        onStopTurn={() => undefined}
        onSubmit={() => undefined}
        providers={providers}
        queuedCount={0}
        queuedPreview={null}
        value={value}
      />
    );
  }

  await act(async () => {
    root?.render(<Harness />);
  });

  const element = container;
  if (!element) {
    throw new Error("Composer test container was not created");
  }

  return {
    element,
    getValue: () => latestValue,
  };
}

async function typeInEditor(text: string) {
  const editor = container?.querySelector('[role="textbox"]');
  expect(editor).toBeInstanceOf(HTMLElement);

  await act(async () => {
    editor!.textContent = text;
    const range = document.createRange();
    range.selectNodeContents(editor!);
    range.collapse(false);
    const selection = window.getSelection();
    selection?.removeAllRanges();
    selection?.addRange(range);
    editor!.dispatchEvent(new Event("input", { bubbles: true }));
  });
}

async function settleReferenceSearch() {
  await act(async () => {
    vi.advanceTimersByTime(180);
    await Promise.resolve();
    await Promise.resolve();
  });
}

function changeInputValue(input: HTMLInputElement, value: string) {
  const valueSetter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")?.set;
  valueSetter?.call(input, value);
  input.dispatchEvent(new Event("input", { bubbles: true }));
  input.dispatchEvent(new Event("change", { bubbles: true }));
}

describe("ChatComposer reference search", () => {
  it("renders checklist entity search results after typing an @ query", async () => {
    vi.useFakeTimers();
    HTMLElement.prototype.scrollIntoView = vi.fn();
    const onSearchReferences = vi.fn(async () => [checklistMention]);

    const { element } = await renderComposer({ onSearchReferences });
    await typeInEditor("@Link");
    await settleReferenceSearch();

    expect(onSearchReferences).toHaveBeenCalledWith("Link", expect.any(AbortSignal));
    const panels = element.querySelectorAll(".chatapp-mention-panel");
    expect(panels).toHaveLength(1);
    expect(panels[0].classList.contains("chatapp-mention-panel--app-picker")).toBe(true);
    const searchInput = element.querySelector('[aria-label="Cerca app o record"]');
    expect(searchInput).toBeInstanceOf(HTMLInputElement);
    expect((searchInput as HTMLInputElement).value).toBe("Link");
    expect(element.textContent).toContain("@Link checklist nella chat con @");
    expect(element.textContent).toContain("checklist · checklist · Checklist operativa");
  });

  it("loads checklist entities when the toolbar app picker opens", async () => {
    vi.useFakeTimers();
    HTMLElement.prototype.scrollIntoView = vi.fn();
    const onSearchReferences = vi.fn(async () => [checklistMention]);
    const { element } = await renderComposer({ onSearchReferences });
    const pickerButton = element.querySelector('[aria-label="App citabili"]');
    expect(pickerButton).toBeInstanceOf(HTMLButtonElement);

    await act(async () => {
      (pickerButton as HTMLButtonElement).click();
    });
    await settleReferenceSearch();

    expect(onSearchReferences).toHaveBeenCalledWith("", expect.any(AbortSignal));
    const panels = element.querySelectorAll(".chatapp-mention-panel");
    expect(panels).toHaveLength(1);
    expect(panels[0].classList.contains("chatapp-mention-panel--app-picker")).toBe(true);
    expect(element.querySelector('[aria-label="Cerca app o record"]')).toBeInstanceOf(HTMLInputElement);
    expect(element.textContent).toContain("@Link checklist nella chat con @");
    expect(element.textContent).toContain("checklist · checklist · Checklist operativa");
  });

  it("uses the shared app picker search input for @ queries and insertion", async () => {
    vi.useFakeTimers();
    HTMLElement.prototype.scrollIntoView = vi.fn();
    const onReferenceAdd = vi.fn();
    const onSearchReferences = vi.fn(async () => [checklistMention]);
    const { element, getValue } = await renderComposer({ onReferenceAdd, onSearchReferences });

    await typeInEditor("@");
    const searchInput = element.querySelector('[aria-label="Cerca app o record"]');
    expect(searchInput).toBeInstanceOf(HTMLInputElement);
    expect(searchInput?.closest(".chatapp-mention-panel")?.classList.contains("chatapp-mention-panel--app-picker")).toBe(true);

    await act(async () => {
      changeInputValue(searchInput as HTMLInputElement, "Link");
    });
    await settleReferenceSearch();

    expect(onSearchReferences).toHaveBeenCalledWith("Link", expect.any(AbortSignal));
    expect(getValue()).toBe("@Link");

    const referenceButton = Array.from(element.querySelectorAll(".chatapp-mention-panel__item")).find((button) =>
      button.textContent?.includes("@Link checklist nella chat con @"),
    );
    expect(referenceButton).toBeInstanceOf(HTMLButtonElement);

    await act(async () => {
      referenceButton!.dispatchEvent(new MouseEvent("mousedown", { bubbles: true, cancelable: true }));
    });

    expect(onReferenceAdd).toHaveBeenCalledWith(checklistReference);
    expect(getValue()).toContain("@Link checklist nella chat con @ [ref:checklist/checklist/check_6f4e74d9f31d]");
  });

  it("searches checklist entities from the toolbar app picker and inserts the selected reference", async () => {
    vi.useFakeTimers();
    HTMLElement.prototype.scrollIntoView = vi.fn();
    const onReferenceAdd = vi.fn();
    const onSearchReferences = vi.fn(async () => [checklistMention]);
    const { element, getValue } = await renderComposer({ onReferenceAdd, onSearchReferences });
    const pickerButton = element.querySelector('[aria-label="App citabili"]');
    expect(pickerButton).toBeInstanceOf(HTMLButtonElement);

    await act(async () => {
      (pickerButton as HTMLButtonElement).click();
    });
    const searchInput = element.querySelector('[aria-label="Cerca app o record"]');
    expect(searchInput).toBeInstanceOf(HTMLInputElement);

    await act(async () => {
      changeInputValue(searchInput as HTMLInputElement, "Link");
    });
    await settleReferenceSearch();

    expect(onSearchReferences).toHaveBeenCalledWith("Link", expect.any(AbortSignal));
    expect(element.textContent).toContain("@Link checklist nella chat con @");

    const referenceButton = Array.from(element.querySelectorAll(".chatapp-mention-panel__item")).find((button) =>
      button.textContent?.includes("@Link checklist nella chat con @"),
    );
    expect(referenceButton).toBeInstanceOf(HTMLButtonElement);

    await act(async () => {
      referenceButton!.dispatchEvent(new MouseEvent("mousedown", { bubbles: true, cancelable: true }));
    });

    expect(onReferenceAdd).toHaveBeenCalledWith(checklistReference);
    expect(getValue()).toContain("@Link checklist nella chat con @ [ref:checklist/checklist/check_6f4e74d9f31d]");
  });

  it("shows reference search failures instead of clearing the panel silently", async () => {
    vi.useFakeTimers();
    HTMLElement.prototype.scrollIntoView = vi.fn();
    const onSearchReferences = vi.fn(async () => {
      throw new Error("search failed");
    });

    const { element } = await renderComposer({ onSearchReferences });
    await typeInEditor("@Link");
    await settleReferenceSearch();

    expect(element.textContent).toContain("Impossibile cercare app o record");
  });
});
