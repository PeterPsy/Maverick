/**
 * @vitest-environment happy-dom
 */
import { act, useState } from "react";
import { createRoot } from "react-dom/client";
import type { Root } from "react-dom/client";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { AgentTypeSummary, AppReference, ProviderItem } from "../api/client";
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

const agents: AgentTypeSummary[] = [
  {
    id: "agent-type-social-video-content-strategist",
    name: "Social Video Content Strategist",
    description: "Turns notes into high-retention social video scripts.",
    role_id: "social-video-content-strategist",
    skill_ids: [],
    trace_verbosity: "compact",
    enabled: true,
  },
];

class FakeDataTransfer {
  dropEffect: DataTransfer["dropEffect"] = "none";
  files: File[] = [];
  types: string[] = [];
  private readonly data = new Map<string, string>();

  getData(type: string) {
    return this.data.get(type.toLowerCase()) || "";
  }

  setData(type: string, value: string) {
    const normalizedType = type.toLowerCase();
    this.data.set(normalizedType, value);
    if (!this.types.includes(normalizedType)) {
      this.types.push(normalizedType);
    }
  }
}

const checklistReference: AppReference = {
  type: "entity",
  app_id: "checklist",
  entity_type: "checklist",
  entity_id: "check_6f4e74d9f31d",
  label: "Checklist link in chat with @",
  summary: "Operational checklist",
  deep_link: "/app/checklist/checklists/check_6f4e74d9f31d",
};

const checklistMention: MentionItem = {
  id: "entity:checklist:checklist:check_6f4e74d9f31d",
  label: checklistReference.label,
  description: "checklist · checklist · Operational checklist",
  kind: "entity",
  reference: checklistReference,
};

const storageFolderReference: AppReference = {
  type: "entity",
  app_id: "storage",
  entity_type: "folder",
  entity_id: "generated:folder%20test/",
  label: "folder test",
  summary: "Storage folder",
  deep_link: "/app/storage/folders/generated/folder%20test",
};

const storageFolderMention: MentionItem = {
  id: "entity:storage:folder:generated:folder%20test/",
  label: storageFolderReference.label,
  description: "storage · folder · Storage folder",
  kind: "entity",
  reference: storageFolderReference,
};

function storageFileMention(index: number): MentionItem {
  const reference: AppReference = {
    type: "entity",
    app_id: "storage",
    entity_type: "file",
    entity_id: `file_${index}`,
    label: `File ${index}`,
    summary: "Storage file",
    deep_link: `/app/storage/files/file_${index}`,
  };
  return {
    id: `entity:storage:file:file_${index}`,
    label: reference.label,
    description: "storage · file · Storage file",
    kind: "entity",
    reference,
  };
}

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
  agentOptions = agents,
  onAddAttachments = () => undefined,
  onReferenceAdd = () => undefined,
  onSearchReferences = async () => [],
  onSelectAgent = () => undefined,
}: {
  agentOptions?: AgentTypeSummary[];
  onAddAttachments?: (files: File[]) => void;
  onReferenceAdd?: (reference: AppReference) => void;
  onSearchReferences?: (query: string, signal: AbortSignal) => Promise<MentionItem[]>;
  onSelectAgent?: (agentTypeId: string) => void;
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
        agents={agentOptions}
        attachments={[]}
        canStopTurn={false}
        disabled={false}
        error={null}
        executionMode={null}
        isSending={false}
        mentionItems={[]}
        onAddAttachments={onAddAttachments}
        onChange={(nextValue) => {
          latestValue = nextValue;
          setValue(nextValue);
        }}
        onReferenceAdd={onReferenceAdd}
        onSearchReferences={onSearchReferences}
        onSelectAgent={onSelectAgent}
        onSelectProvider={() => undefined}
        onRemoveAttachment={() => undefined}
        onStopTurn={() => undefined}
        onSubmit={() => undefined}
        providers={providers}
        queuedCount={0}
        queuedPreview={null}
        selectedAgentTypeId=""
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

async function dropOnEditor(dataTransfer: FakeDataTransfer) {
  const editor = container?.querySelector('[role="textbox"]');
  expect(editor).toBeInstanceOf(HTMLElement);

  await act(async () => {
    const event = new Event("drop", { bubbles: true, cancelable: true });
    Object.defineProperty(event, "dataTransfer", { value: dataTransfer });
    editor!.dispatchEvent(event);
  });
}

async function dragOverEditor(dataTransfer: FakeDataTransfer) {
  const editor = container?.querySelector('[role="textbox"]');
  expect(editor).toBeInstanceOf(HTMLElement);

  await act(async () => {
    const event = new Event("dragover", { bubbles: true, cancelable: true });
    Object.defineProperty(event, "dataTransfer", { value: dataTransfer });
    editor!.dispatchEvent(event);
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
  it("opens the agent selector and selects an agent runner", async () => {
    const onSelectAgent = vi.fn();
    const { element } = await renderComposer({ onSelectAgent });
    const agentButton = element.querySelector('[aria-label="Agent runner: Default Chat"]');
    expect(agentButton).toBeInstanceOf(HTMLButtonElement);

    await act(async () => {
      (agentButton as HTMLButtonElement).click();
    });

    expect(element.textContent).toContain("Social Video Content Strategist");
    const socialAgent = Array.from(element.querySelectorAll(".chatapp-agent-menu__item")).find((button) =>
      button.textContent?.includes("Social Video Content Strategist"),
    );
    expect(socialAgent).toBeInstanceOf(HTMLButtonElement);

    await act(async () => {
      (socialAgent as HTMLButtonElement).click();
    });

    expect(onSelectAgent).toHaveBeenCalledWith("agent-type-social-video-content-strategist");
  });

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
    const searchInput = element.querySelector('[aria-label="Search apps, files, or folders"]');
    expect(searchInput).toBeInstanceOf(HTMLInputElement);
    expect((searchInput as HTMLInputElement).value).toBe("Link");
    expect(element.textContent).toContain("@Checklist link in chat with @");
    expect(element.textContent).toContain("checklist · checklist · Operational checklist");
  });

  it("loads checklist entities when the toolbar app picker opens", async () => {
    vi.useFakeTimers();
    HTMLElement.prototype.scrollIntoView = vi.fn();
    const onSearchReferences = vi.fn(async () => [checklistMention]);
    const { element } = await renderComposer({ onSearchReferences });
    const pickerButton = element.querySelector('[aria-label="Apps and references"]');
    expect(pickerButton).toBeInstanceOf(HTMLButtonElement);

    await act(async () => {
      (pickerButton as HTMLButtonElement).click();
    });
    await settleReferenceSearch();

    expect(onSearchReferences).toHaveBeenCalledWith("", expect.any(AbortSignal));
    const panels = element.querySelectorAll(".chatapp-mention-panel");
    expect(panels).toHaveLength(1);
    expect(panels[0].classList.contains("chatapp-mention-panel--app-picker")).toBe(true);
    expect(element.querySelector('[aria-label="Search apps, files, or folders"]')).toBeInstanceOf(HTMLInputElement);
    expect(element.textContent).toContain("@Checklist link in chat with @");
    expect(element.textContent).toContain("checklist · checklist · Operational checklist");
  });

  it("keeps storage folders visible after the first storage file references", async () => {
    vi.useFakeTimers();
    HTMLElement.prototype.scrollIntoView = vi.fn();
    const onSearchReferences = vi.fn(async () => [
      ...Array.from({ length: 8 }, (_item, index) => storageFileMention(index + 1)),
      storageFolderMention,
    ]);
    const { element } = await renderComposer({ onSearchReferences });
    const pickerButton = element.querySelector('[aria-label="Apps and references"]');
    expect(pickerButton).toBeInstanceOf(HTMLButtonElement);

    await act(async () => {
      (pickerButton as HTMLButtonElement).click();
    });
    await settleReferenceSearch();

    expect(onSearchReferences).toHaveBeenCalledWith("", expect.any(AbortSignal));
    expect(element.textContent).toContain("@folder test");
    expect(element.textContent).toContain("storage · folder · Storage folder");
  });

  it("uses the shared app picker search input for @ queries and insertion", async () => {
    vi.useFakeTimers();
    HTMLElement.prototype.scrollIntoView = vi.fn();
    const onReferenceAdd = vi.fn();
    const onSearchReferences = vi.fn(async () => [checklistMention]);
    const { element, getValue } = await renderComposer({ onReferenceAdd, onSearchReferences });

    await typeInEditor("@");
    const searchInput = element.querySelector('[aria-label="Search apps, files, or folders"]');
    expect(searchInput).toBeInstanceOf(HTMLInputElement);
    expect(searchInput?.closest(".chatapp-mention-panel")?.classList.contains("chatapp-mention-panel--app-picker")).toBe(true);

    await act(async () => {
      changeInputValue(searchInput as HTMLInputElement, "Link");
    });
    await settleReferenceSearch();

    expect(onSearchReferences).toHaveBeenCalledWith("Link", expect.any(AbortSignal));
    expect(getValue()).toBe("@Link");

    const referenceButton = Array.from(element.querySelectorAll(".chatapp-mention-panel__item")).find((button) =>
      button.textContent?.includes("@Checklist link in chat with @"),
    );
    expect(referenceButton).toBeInstanceOf(HTMLButtonElement);

    await act(async () => {
      referenceButton!.dispatchEvent(new MouseEvent("mousedown", { bubbles: true, cancelable: true }));
    });

    expect(onReferenceAdd).toHaveBeenCalledWith(checklistReference);
    expect(getValue()).toContain("@Checklist link in chat with @ [ref:checklist/checklist/check_6f4e74d9f31d]");
  });

  it("searches checklist entities from the toolbar app picker and inserts the selected reference", async () => {
    vi.useFakeTimers();
    HTMLElement.prototype.scrollIntoView = vi.fn();
    const onReferenceAdd = vi.fn();
    const onSearchReferences = vi.fn(async () => [checklistMention]);
    const { element, getValue } = await renderComposer({ onReferenceAdd, onSearchReferences });
    const pickerButton = element.querySelector('[aria-label="Apps and references"]');
    expect(pickerButton).toBeInstanceOf(HTMLButtonElement);

    await act(async () => {
      (pickerButton as HTMLButtonElement).click();
    });
    const searchInput = element.querySelector('[aria-label="Search apps, files, or folders"]');
    expect(searchInput).toBeInstanceOf(HTMLInputElement);

    await act(async () => {
      changeInputValue(searchInput as HTMLInputElement, "Link");
    });
    await settleReferenceSearch();

    expect(onSearchReferences).toHaveBeenCalledWith("Link", expect.any(AbortSignal));
    expect(element.textContent).toContain("@Checklist link in chat with @");

    const referenceButton = Array.from(element.querySelectorAll(".chatapp-mention-panel__item")).find((button) =>
      button.textContent?.includes("@Checklist link in chat with @"),
    );
    expect(referenceButton).toBeInstanceOf(HTMLButtonElement);

    await act(async () => {
      referenceButton!.dispatchEvent(new MouseEvent("mousedown", { bubbles: true, cancelable: true }));
    });

    expect(onReferenceAdd).toHaveBeenCalledWith(checklistReference);
    expect(getValue()).toContain("@Checklist link in chat with @ [ref:checklist/checklist/check_6f4e74d9f31d]");
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

    expect(element.textContent).toContain("Unable to search apps or records");
  });

  it("inserts dragged Storage items as reference mentions", async () => {
    const onReferenceAdd = vi.fn();
    const { getValue } = await renderComposer({ onReferenceAdd });
    const dataTransfer = new FakeDataTransfer();
    dataTransfer.setData(
      "application/x-maverick-storage-selection",
      JSON.stringify({
        owner_app_id: "storage",
        files: [
          {
            file_id: "file_123",
            name: "report.md",
            owner_app_id: "storage",
            preview_kind: "markdown",
            relative_path: "Reports/report.md",
            role: "generated",
            workspace_relative_path: "storage/generated/Reports/report.md",
          },
        ],
        folders: [
          {
            folder_id: "generated:Client Docs/",
            name: "Client Docs",
            owner_app_id: "storage",
            relative_path: "Client Docs",
            role: "generated",
            workspace_relative_path: "storage/generated/Client Docs",
          },
        ],
      }),
    );

    await dropOnEditor(dataTransfer);

    expect(getValue()).toBe("@report.md [ref:storage/file/file_123] @Client Docs [ref:storage/folder/generated:Client%20Docs/] ");
    expect(onReferenceAdd).toHaveBeenCalledWith({
      type: "entity",
      app_id: "storage",
      entity_type: "file",
      entity_id: "file_123",
      label: "report.md",
      summary: "markdown file in generated",
      deep_link: "/app/storage/files/file_123",
    });
    expect(onReferenceAdd).toHaveBeenCalledWith({
      type: "entity",
      app_id: "storage",
      entity_type: "folder",
      entity_id: "generated:Client%20Docs/",
      label: "Client Docs",
      summary: "Storage folder in generated",
      deep_link: "/app/storage/folders/generated/Client%20Docs",
    });
  });

  it("does not render a file drop overlay inside the composer", async () => {
    const { element } = await renderComposer();
    const dataTransfer = new FakeDataTransfer();
    dataTransfer.types.push("Files");
    dataTransfer.files = [new File(["notes"], "notes.txt", { type: "text/plain" })];

    await dragOverEditor(dataTransfer);

    expect(element.querySelector(".chatapp-chat-dropzone")).toBeNull();
  });
});
