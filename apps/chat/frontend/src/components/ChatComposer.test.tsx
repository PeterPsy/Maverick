/**
 * @vitest-environment happy-dom
 */
import { act, useState } from "react";
import { createRoot } from "react-dom/client";
import type { Root } from "react-dom/client";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ApiError, transcribeSpeechBlob } from "../api/client";
import type { AgentTypeSummary, AppReference, MultiAgentComposerMode, ProviderItem } from "../api/client";
import type { MentionItem } from "../lib/mentions";
import { ChatComposer, type ExecutionMode } from "./ChatComposer";

vi.mock("../api/client", async () => {
  const actual = await vi.importActual<typeof import("../api/client")>("../api/client");
  return {
    ...actual,
    transcribeSpeechBlob: vi.fn(),
  };
});

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

const searchableAgents: AgentTypeSummary[] = [
  ...agents,
  {
    id: "agent-type-ops-reviewer",
    name: "Operations Reviewer",
    description: "Finds workflow gaps before customer handoff.",
    role_id: "ops-reviewer",
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
  vi.mocked(transcribeSpeechBlob).mockReset();
  root?.unmount();
  root = null;
  container?.remove();
  container = null;
  Object.defineProperty(navigator, "permissions", {
    configurable: true,
    value: undefined,
  });
  Object.defineProperty(document, "permissionsPolicy", {
    configurable: true,
    value: undefined,
  });
  Object.defineProperty(document, "featurePolicy", {
    configurable: true,
    value: undefined,
  });
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

async function renderComposer({
  agentOptions = agents,
  onAddAttachments = () => undefined,
  mentionItems = [],
  onReferenceAdd = () => undefined,
  onSearchReferences = async () => [],
  onSelectMultiAgentMode = () => undefined,
  onSelectAgent = () => undefined,
  executionMode = null,
  multiAgentGroupChatEnabled = false,
  multiAgentMode = "off",
  onSubmit = () => undefined,
  transcriptionChunkedDictationSupported = false,
  transcriptionProviderAppId = "",
  transcriptionProviderAvailable = false,
  agentCatalogLoading = false,
}: {
  agentOptions?: AgentTypeSummary[];
  agentCatalogLoading?: boolean;
  mentionItems?: MentionItem[];
  onAddAttachments?: (files: File[]) => void;
  onReferenceAdd?: (reference: AppReference) => void;
  onSearchReferences?: (query: string, signal: AbortSignal) => Promise<MentionItem[]>;
  onSelectMultiAgentMode?: (mode: MultiAgentComposerMode) => void;
  onSelectAgent?: (agentTypeId: string) => void;
  executionMode?: ExecutionMode | null;
  multiAgentGroupChatEnabled?: boolean;
  multiAgentMode?: MultiAgentComposerMode;
  onSubmit?: () => void;
  transcriptionChunkedDictationSupported?: boolean;
  transcriptionProviderAppId?: string;
  transcriptionProviderAvailable?: boolean;
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
        agentCatalogLoading={agentCatalogLoading}
        agents={agentOptions}
        attachments={[]}
        canStopTurn={false}
        disabled={false}
        error={null}
        executionMode={executionMode}
        isSending={false}
        mentionItems={mentionItems}
        multiAgentBudgetLabel="1 worker · 1 turn · 1 tool call"
        multiAgentGroupChatEnabled={multiAgentGroupChatEnabled}
        multiAgentMode={multiAgentMode}
        onAddAttachments={onAddAttachments}
        onChange={(nextValue) => {
          latestValue = nextValue;
          setValue(nextValue);
        }}
        onReferenceAdd={onReferenceAdd}
        onSearchReferences={onSearchReferences}
        onSelectMultiAgentMode={onSelectMultiAgentMode}
        onSelectAgent={onSelectAgent}
        onSelectProvider={() => undefined}
        onRemoveAttachment={() => undefined}
        onStopTurn={() => undefined}
        onSubmit={onSubmit}
        providers={providers}
        queuedCount={0}
        queuedPreview={null}
        selectedAgentTypeId=""
        transcriptionChunkedDictationSupported={transcriptionChunkedDictationSupported}
        transcriptionProviderAppId={transcriptionProviderAppId}
        transcriptionProviderAvailable={transcriptionProviderAvailable}
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

describe("agent selector loading", () => {
  it("shows a loading label without disabling the composer", async () => {
    const { element } = await renderComposer({ agentCatalogLoading: true, agentOptions: [] });

    expect(element.querySelector('[aria-label="Agent runner: Loading agents..."]')).toBeTruthy();
    expect(element.querySelector('[role="textbox"]')?.getAttribute("aria-disabled")).toBe("false");
  });
});

function mockMediaRecorder() {
  const stopTrack = vi.fn();
  const stream = { getTracks: () => [{ stop: stopTrack }] };
  const getUserMedia = vi.fn(async () => stream);
  class FakeMediaRecorder {
    static isTypeSupported = vi.fn((mimeType: string) => mimeType === "audio/webm");
    mimeType = "audio/webm";
    ondataavailable: ((event: { data: Blob }) => void) | null = null;
    onerror: (() => void) | null = null;
    onstop: (() => void) | null = null;

    constructor() {}

    start() {
      this.ondataavailable?.({ data: new Blob([new Uint8Array([1, 2, 3, 4, 5])], { type: "audio/webm" }) });
    }

    stop() {
      this.onstop?.();
    }
  }
  vi.stubGlobal("MediaRecorder", FakeMediaRecorder);
  Object.defineProperty(navigator, "mediaDevices", {
    configurable: true,
    value: { getUserMedia },
  });
  return { getUserMedia, stopTrack };
}

function mockMicrophoneDenied() {
  class FakeMediaRecorder {
    static isTypeSupported = vi.fn((mimeType: string) => mimeType === "audio/webm");
  }
  const deniedError = Object.assign(new Error("Permission denied"), { name: "NotAllowedError" });
  const getUserMedia = vi.fn(async () => {
    throw deniedError;
  });
  vi.stubGlobal("MediaRecorder", FakeMediaRecorder);
  Object.defineProperty(navigator, "mediaDevices", {
    configurable: true,
    value: { getUserMedia },
  });
  return { getUserMedia };
}

function mockMicrophonePermission(state: PermissionState) {
  const query = vi.fn(async () => ({ state }));
  Object.defineProperty(navigator, "permissions", {
    configurable: true,
    value: { query },
  });
  return { query };
}

function mockMicrophoneFramePolicy(allowed: boolean) {
  const allowsFeature = vi.fn(() => allowed);
  Object.defineProperty(document, "permissionsPolicy", {
    configurable: true,
    value: { allowsFeature },
  });
  return { allowsFeature };
}

function editorElement(): HTMLElement {
  const editor = container?.querySelector('[role="textbox"]');
  expect(editor).toBeInstanceOf(HTMLElement);
  return editor as HTMLElement;
}

async function typeInEditor(text: string) {
  const editor = editorElement();

  await act(async () => {
    editor.focus();
    editor.textContent = text;
    const range = document.createRange();
    range.selectNodeContents(editor);
    range.collapse(false);
    const selection = window.getSelection();
    selection?.removeAllRanges();
    selection?.addRange(range);
    editor.dispatchEvent(new Event("input", { bubbles: true }));
  });
}

async function selectEditorRange(start: number, end: number) {
  const editor = editorElement();
  const textNode = editor.firstChild;
  expect(textNode?.nodeType).toBe(Node.TEXT_NODE);

  await act(async () => {
    editor.focus();
    const range = document.createRange();
    range.setStart(textNode!, start);
    range.setEnd(textNode!, end);
    const selection = window.getSelection();
    selection?.removeAllRanges();
    selection?.addRange(range);
  });
}

async function keyDownEditor(init: KeyboardEventInit) {
  const editor = editorElement();
  await act(async () => {
    editor.dispatchEvent(new KeyboardEvent("keydown", { bubbles: true, cancelable: true, ...init }));
  });
}

async function pasteTextInEditor(text: string) {
  const editor = editorElement();
  await act(async () => {
    const event = new Event("paste", { bubbles: true, cancelable: true });
    Object.defineProperty(event, "clipboardData", {
      value: {
        files: [],
        getData: (type: string) => (type === "text/plain" ? text : ""),
      },
    });
    editor.dispatchEvent(event);
  });
}

function mockMobileInput(matches: boolean) {
  vi.stubGlobal(
    "matchMedia",
    vi.fn((query: string) => ({
      addEventListener: vi.fn(),
      addListener: vi.fn(),
      dispatchEvent: vi.fn(),
      matches: matches && (query === "(pointer: coarse)" || query === "(max-width: 720px)"),
      media: query,
      onchange: null,
      removeEventListener: vi.fn(),
      removeListener: vi.fn(),
    })),
  );
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

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((resolvePromise, rejectPromise) => {
    resolve = resolvePromise;
    reject = rejectPromise;
  });
  return { promise, reject, resolve };
}

async function waitForComposerAssertion(assertion: () => void) {
  let lastError: unknown;
  for (let attempt = 0; attempt < 20; attempt += 1) {
    try {
      assertion();
      return;
    } catch (error) {
      lastError = error;
      await act(async () => {
        await new Promise((resolve) => setTimeout(resolve, 0));
      });
    }
  }
  throw lastError;
}

function changeInputValue(input: HTMLInputElement, value: string) {
  const valueSetter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")?.set;
  valueSetter?.call(input, value);
  input.dispatchEvent(new Event("input", { bubbles: true }));
  input.dispatchEvent(new Event("change", { bubbles: true }));
}

function dispatchPointerDown(target: Element, pointerType: string) {
  const event = new Event("pointerdown", { bubbles: true, cancelable: true });
  Object.defineProperty(event, "pointerType", { value: pointerType });
  target.dispatchEvent(event);
}

describe("ChatComposer reference search", () => {
  it("preserves a desktop mouse text selection after mouseup", async () => {
    await renderComposer();
    await typeInEditor("hello world");
    await selectEditorRange(0, 5);

    await act(async () => {
      editorElement().dispatchEvent(new MouseEvent("mouseup", { bubbles: true, cancelable: true }));
    });

    expect(window.getSelection()?.toString()).toBe("hello");
  });

  it("inserts a newline for Shift+Enter without submitting", async () => {
    const onSubmit = vi.fn();
    const { getValue } = await renderComposer({ onSubmit });
    await typeInEditor("hello");

    await keyDownEditor({ key: "Enter", shiftKey: true });

    expect(getValue()).toBe("hello\n");
    expect(onSubmit).not.toHaveBeenCalled();
  });

  it("uses Enter as a newline on mobile composer input", async () => {
    mockMobileInput(true);
    const onSubmit = vi.fn();
    const { getValue } = await renderComposer({ onSubmit });
    await typeInEditor("hello");

    await keyDownEditor({ key: "Enter" });

    expect(getValue()).toBe("hello\n");
    expect(onSubmit).not.toHaveBeenCalled();
  });

  it("submits with Enter on desktop composer input", async () => {
    mockMobileInput(false);
    const onSubmit = vi.fn();
    await renderComposer({ onSubmit });
    await typeInEditor("hello");

    await keyDownEditor({ key: "Enter" });

    expect(onSubmit).toHaveBeenCalledTimes(1);
  });

  it("undoes and redoes coalesced composer typing", async () => {
    const { getValue } = await renderComposer();
    await typeInEditor("hello");

    await keyDownEditor({ ctrlKey: true, key: "z" });
    expect(getValue()).toBe("");

    await keyDownEditor({ ctrlKey: true, key: "Z", shiftKey: true });
    expect(getValue()).toBe("hello");

    await keyDownEditor({ ctrlKey: true, key: "z" });
    expect(getValue()).toBe("");

    await keyDownEditor({ ctrlKey: true, key: "y" });
    expect(getValue()).toBe("hello");
  });

  it("undoes and redoes programmatic newline edits", async () => {
    const { getValue } = await renderComposer();
    await typeInEditor("hello");
    await keyDownEditor({ key: "Enter", shiftKey: true });

    expect(getValue()).toBe("hello\n");

    await keyDownEditor({ metaKey: true, key: "z" });
    expect(getValue()).toBe("hello");

    await keyDownEditor({ metaKey: true, key: "Z", shiftKey: true });
    expect(getValue()).toBe("hello\n");
  });

  it("keeps a completed app mention from reopening the picker before submit", async () => {
    mockMobileInput(false);
    const onSubmit = vi.fn();
    const onSearchReferences = vi.fn(async () => []);
    const storageApp: MentionItem = {
      id: "storage",
      label: "Storage",
      description: "Files and folders",
      kind: "app",
    };
    const { element } = await renderComposer({ mentionItems: [storageApp], onSearchReferences, onSubmit });

    await typeInEditor("@Storage message");
    expect(element.querySelector('[aria-label="Search apps and references"]')).toBeNull();

    await keyDownEditor({ key: "Enter" });

    expect(onSubmit).toHaveBeenCalledTimes(1);
    expect(onSearchReferences).not.toHaveBeenCalled();
  });

  it("normalizes pasted multiline text as plain composer text", async () => {
    const { getValue } = await renderComposer();
    await typeInEditor("first");

    await pasteTextInEditor(" second\r\nthird");

    expect(getValue()).toBe("first second\nthird");
  });

  it("undoes and redoes pasted text as one composer edit", async () => {
    const { getValue } = await renderComposer();
    await typeInEditor("first");
    await pasteTextInEditor(" second\r\nthird");

    await keyDownEditor({ ctrlKey: true, key: "z" });
    expect(getValue()).toBe("first");

    await keyDownEditor({ ctrlKey: true, key: "y" });
    expect(getValue()).toBe("first second\nthird");
  });

  it("replaces the selected composer range with pasted plain text", async () => {
    const { getValue } = await renderComposer();
    await typeInEditor("hello world");
    await selectEditorRange(6, 11);

    await pasteTextInEditor("Maverick");

    expect(getValue()).toBe("hello Maverick");
  });

  it("undoes and redoes app mention insertion", async () => {
    const storageApp: MentionItem = {
      id: "storage",
      label: "Storage",
      description: "Files and folders",
      kind: "app",
    };
    const { getValue } = await renderComposer({ mentionItems: [storageApp] });
    await typeInEditor("@Sto");

    await keyDownEditor({ key: "Enter" });
    expect(getValue()).toBe("@Storage ");

    await keyDownEditor({ ctrlKey: true, key: "z" });
    expect(getValue()).toBe("@Sto");

    await keyDownEditor({ ctrlKey: true, key: "Z", shiftKey: true });
    expect(getValue()).toBe("@Storage ");
  });

  it("keeps the caret visible after a long paste", async () => {
    const { getValue } = await renderComposer();
    await typeInEditor("start ");
    const editor = editorElement();
    Object.defineProperty(editor, "clientHeight", { configurable: true, value: 80 });
    Object.defineProperty(editor, "scrollHeight", { configurable: true, value: 640 });

    await pasteTextInEditor("longpaste".repeat(140));

    expect(getValue()).toBe(`start ${"longpaste".repeat(140)}`);
    expect(editor.scrollTop).toBe(640);
  });

  it("keeps dictation disabled when no transcription provider is available", async () => {
    const { element } = await renderComposer();

    const button = element.querySelector('[aria-label="Dictate"]');

    expect(button).toBeInstanceOf(HTMLButtonElement);
    expect((button as HTMLButtonElement).disabled).toBe(true);
  });

  it("records microphone audio and inserts the transcript without submitting", async () => {
    const onSubmit = vi.fn();
    const { element, getValue } = await renderComposer({
      onSubmit,
      transcriptionProviderAppId: "speech",
      transcriptionProviderAvailable: true,
    });
    const media = mockMediaRecorder();
    vi.mocked(transcribeSpeechBlob).mockResolvedValue({ text: "Hello transcript", retention: "metadata_only" });

    await act(async () => {
      element.querySelector<HTMLButtonElement>('[aria-label="Dictate"]')?.click();
      await Promise.resolve();
    });
    expect(element.querySelector<HTMLButtonElement>('[aria-label="Stop dictation"]')).toBeInstanceOf(HTMLButtonElement);
    await act(async () => {
      element.querySelector<HTMLButtonElement>('[aria-label="Stop dictation"]')?.click();
      await Promise.resolve();
      await Promise.resolve();
    });
    await waitForComposerAssertion(() => {
      const options = vi.mocked(transcribeSpeechBlob).mock.calls[0]?.[2] as Record<string, unknown>;
      expect(options).toMatchObject({ dictation: true, language: undefined, profile: "fast" });
      expect(options).not.toHaveProperty("chunkIndex");
      expect(options).not.toHaveProperty("sessionId");
      expect(getValue()).toBe("Hello transcript");
    });

    expect(media.getUserMedia).toHaveBeenCalledWith({
      audio: { autoGainControl: true, echoCancellation: true, noiseSuppression: true },
    });
    expect(media.stopTrack).toHaveBeenCalled();
    expect(onSubmit).not.toHaveBeenCalled();
  });

  it("reuses a high-confidence detected dictation language on the next recording", async () => {
    const { element, getValue } = await renderComposer({
      transcriptionProviderAppId: "speech",
      transcriptionProviderAvailable: true,
    });
    mockMediaRecorder();
    vi.mocked(transcribeSpeechBlob)
      .mockResolvedValueOnce({ text: "Primo testo", language: "it", language_probability: 0.95, retention: "metadata_only" })
      .mockResolvedValueOnce({ text: "Secondo testo", language: "it", language_probability: 0.96, retention: "metadata_only" })
      .mockResolvedValueOnce({ text: "Third text", language: "en", language_probability: 0.93, retention: "metadata_only" });

    await act(async () => {
      element.querySelector<HTMLButtonElement>('[aria-label="Dictate"]')?.click();
      await Promise.resolve();
    });
    await act(async () => {
      element.querySelector<HTMLButtonElement>('[aria-label="Stop dictation"]')?.click();
      await Promise.resolve();
      await Promise.resolve();
    });
    await waitForComposerAssertion(() => {
      expect(transcribeSpeechBlob).toHaveBeenCalledTimes(1);
      expect(getValue()).toBe("Primo testo");
    });

    await act(async () => {
      element.querySelector<HTMLButtonElement>('[aria-label="Dictate"]')?.click();
      await Promise.resolve();
    });
    await act(async () => {
      element.querySelector<HTMLButtonElement>('[aria-label="Stop dictation"]')?.click();
      await Promise.resolve();
      await Promise.resolve();
    });

    await waitForComposerAssertion(() => {
      const firstOptions = vi.mocked(transcribeSpeechBlob).mock.calls[0]?.[2] as Record<string, unknown>;
      const secondOptions = vi.mocked(transcribeSpeechBlob).mock.calls[1]?.[2] as Record<string, unknown>;
      expect(firstOptions).toMatchObject({ dictation: true, language: undefined, profile: "fast" });
      expect(firstOptions).not.toHaveProperty("sessionId");
      expect(secondOptions).toMatchObject({ dictation: true, language: "it", profile: "fast" });
      expect(secondOptions).not.toHaveProperty("sessionId");
    });

    await act(async () => {
      element.querySelector<HTMLButtonElement>('[aria-label="Dictate"]')?.click();
      await Promise.resolve();
    });
    await act(async () => {
      element.querySelector<HTMLButtonElement>('[aria-label="Stop dictation"]')?.click();
      await Promise.resolve();
      await Promise.resolve();
    });

    await waitForComposerAssertion(() => {
      const thirdOptions = vi.mocked(transcribeSpeechBlob).mock.calls[2]?.[2] as Record<string, unknown>;
      expect(thirdOptions).toMatchObject({ dictation: true, language: undefined, profile: "fast" });
      expect(thirdOptions).not.toHaveProperty("sessionId");
    });
  });

  it("shows a microphone permission message when the browser blocks getUserMedia", async () => {
    const { element } = await renderComposer({
      transcriptionProviderAppId: "speech",
      transcriptionProviderAvailable: true,
    });
    const media = mockMicrophoneDenied();

    await act(async () => {
      element.querySelector<HTMLButtonElement>('[aria-label="Dictate"]')?.click();
      await Promise.resolve();
    });

    expect(media.getUserMedia).toHaveBeenCalledWith({
      audio: { autoGainControl: true, echoCancellation: true, noiseSuppression: true },
    });
    expect(element.textContent).toContain("Microphone permission was blocked");
  });

  it("still asks getUserMedia when the Permissions API reports denied", async () => {
    const { element, getValue } = await renderComposer({
      transcriptionProviderAppId: "speech",
      transcriptionProviderAvailable: true,
    });
    mockMicrophonePermission("denied");
    const media = mockMediaRecorder();
    vi.mocked(transcribeSpeechBlob).mockResolvedValue({ text: "Permission query was stale", retention: "metadata_only" });

    await act(async () => {
      element.querySelector<HTMLButtonElement>('[aria-label="Dictate"]')?.click();
      await Promise.resolve();
    });
    expect(media.getUserMedia).toHaveBeenCalledWith({
      audio: { autoGainControl: true, echoCancellation: true, noiseSuppression: true },
    });

    await act(async () => {
      element.querySelector<HTMLButtonElement>('[aria-label="Stop dictation"]')?.click();
      await Promise.resolve();
      await Promise.resolve();
    });
    await waitForComposerAssertion(() => {
      expect(getValue()).toBe("Permission query was stale");
    });
  });

  it("shows when the shell frame policy blocks microphone access", async () => {
    const { element } = await renderComposer({
      transcriptionProviderAppId: "speech",
      transcriptionProviderAvailable: true,
    });
    mockMicrophoneFramePolicy(false);
    mockMicrophoneDenied();

    await act(async () => {
      element.querySelector<HTMLButtonElement>('[aria-label="Dictate"]')?.click();
      await Promise.resolve();
    });

    expect(element.textContent).toContain("Maverick shell is blocking microphone access for Chat");
  });

  it("shows API status details when microphone transcription fails", async () => {
    const { element } = await renderComposer({
      transcriptionProviderAppId: "speech",
      transcriptionProviderAvailable: true,
    });
    mockMediaRecorder();
    vi.mocked(transcribeSpeechBlob).mockRejectedValue(new ApiError("provider_unavailable", { path: "/api/apps/speech/backend", status: 503 }));

    await act(async () => {
      element.querySelector<HTMLButtonElement>('[aria-label="Dictate"]')?.click();
      await Promise.resolve();
    });
    await act(async () => {
      element.querySelector<HTMLButtonElement>('[aria-label="Stop dictation"]')?.click();
      await Promise.resolve();
      await Promise.resolve();
    });

    await waitForComposerAssertion(() => {
      expect(element.textContent).toContain("Speech transcription request failed (503): provider_unavailable");
    });
  });

  it("keeps focus in the composer when an @ mention opens suggestions from typing", async () => {
    vi.useFakeTimers();
    HTMLElement.prototype.scrollIntoView = vi.fn();
    const { element } = await renderComposer();

    await typeInEditor("@");

    expect(element.querySelector('[aria-label="Search apps and references"]')).toBeInstanceOf(HTMLInputElement);
    expect(element.querySelector(".chatapp-mention-panel__header")).toBeNull();
    expect(element.querySelector(".chatapp-mention-panel__search-label")).toBeNull();
    expect(document.activeElement).toBe(editorElement());
  });

  it("does not submit from the @ picker search input when Enter has no result to select", async () => {
    vi.useFakeTimers();
    HTMLElement.prototype.scrollIntoView = vi.fn();
    const onSubmit = vi.fn();
    const onSearchReferences = vi.fn(async () => []);
    const { element } = await renderComposer({ onSearchReferences, onSubmit });
    await typeInEditor("@Missing");
    await settleReferenceSearch();
    const searchInput = element.querySelector('[aria-label="Search apps and references"]');
    expect(searchInput).toBeInstanceOf(HTMLInputElement);

    await act(async () => {
      searchInput!.dispatchEvent(new KeyboardEvent("keydown", { bubbles: true, cancelable: true, key: "Enter" }));
    });

    expect(onSubmit).not.toHaveBeenCalled();
  });

  it("lets Tab move focus from the @ picker search input when there are no results", async () => {
    vi.useFakeTimers();
    HTMLElement.prototype.scrollIntoView = vi.fn();
    const onSearchReferences = vi.fn(async () => []);
    const { element } = await renderComposer({ onSearchReferences });
    await typeInEditor("@Missing");
    await settleReferenceSearch();
    const searchInput = element.querySelector('[aria-label="Search apps and references"]');
    expect(searchInput).toBeInstanceOf(HTMLInputElement);
    const tabEvent = new KeyboardEvent("keydown", { bubbles: true, cancelable: true, key: "Tab" });

    await act(async () => {
      searchInput!.dispatchEvent(tabEvent);
    });

    expect(tabEvent.defaultPrevented).toBe(false);
  });

  it("does not select an @ suggestion while IME composition is confirming", async () => {
    vi.useFakeTimers();
    HTMLElement.prototype.scrollIntoView = vi.fn();
    const onReferenceAdd = vi.fn();
    const onSearchReferences = vi.fn(async () => [checklistMention]);
    const { getValue } = await renderComposer({ onReferenceAdd, onSearchReferences });
    await typeInEditor("@Link");
    await settleReferenceSearch();
    const enterEvent = new KeyboardEvent("keydown", { bubbles: true, cancelable: true, key: "Enter" });
    Object.defineProperty(enterEvent, "isComposing", { value: true });

    await act(async () => {
      editorElement().dispatchEvent(enterEvent);
    });

    expect(onReferenceAdd).not.toHaveBeenCalled();
    expect(enterEvent.defaultPrevented).toBe(false);
    expect(getValue()).toBe("@Link");
  });

  it("does not select an @ suggestion from search input while IME composition is confirming", async () => {
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
    const searchInput = element.querySelector('[aria-label="Search apps and references"]');
    expect(searchInput).toBeInstanceOf(HTMLInputElement);
    await act(async () => {
      changeInputValue(searchInput as HTMLInputElement, "Link");
    });
    await settleReferenceSearch();
    const enterEvent = new KeyboardEvent("keydown", { bubbles: true, cancelable: true, key: "Enter" });
    Object.defineProperty(enterEvent, "isComposing", { value: true });

    await act(async () => {
      searchInput!.dispatchEvent(enterEvent);
    });

    expect(onReferenceAdd).not.toHaveBeenCalled();
    expect(enterEvent.defaultPrevented).toBe(false);
    expect(getValue()).toBe("");
  });

  it("opens the agent selector and selects an agent runner", async () => {
    const onSelectAgent = vi.fn();
    const { element } = await renderComposer({ onSelectAgent });
    const agentButton = element.querySelector('[aria-label="Agent runner: Default Chat"]');
    expect(agentButton).toBeInstanceOf(HTMLButtonElement);

    await act(async () => {
      (agentButton as HTMLButtonElement).click();
    });

    expect(element.querySelector(".chatapp-agent-menu__header")).toBeNull();
    expect(element.querySelector(".chatapp-agent-menu__search-label")).toBeNull();
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

  it("filters agent runners while keeping Default Chat available", async () => {
    const { element } = await renderComposer({ agentOptions: searchableAgents });
    const agentButton = element.querySelector('[aria-label="Agent runner: Default Chat"]');
    expect(agentButton).toBeInstanceOf(HTMLButtonElement);
    const agentButtonElement = agentButton as HTMLButtonElement;

    await act(async () => {
      agentButtonElement.click();
    });
    const searchInput = element.querySelector('[aria-label="Search agents"]');
    expect(searchInput).toBeInstanceOf(HTMLInputElement);

    await act(async () => {
      changeInputValue(searchInput as HTMLInputElement, "ops-reviewer");
    });

    expect(element.textContent).toContain("Default Chat");
    expect(element.textContent).toContain("Operations Reviewer");
    expect(element.textContent).not.toContain("Social Video Content Strategist");
    expect(element.textContent).not.toContain("No agent catalog available");
  });

  it("shows a filtered empty state without hiding Default Chat", async () => {
    const { element } = await renderComposer({ agentOptions: searchableAgents });
    const agentButton = element.querySelector('[aria-label="Agent runner: Default Chat"]');
    expect(agentButton).toBeInstanceOf(HTMLButtonElement);
    const agentButtonElement = agentButton as HTMLButtonElement;

    await act(async () => {
      agentButtonElement.click();
    });
    const searchInput = element.querySelector('[aria-label="Search agents"]');
    expect(searchInput).toBeInstanceOf(HTMLInputElement);

    await act(async () => {
      changeInputValue(searchInput as HTMLInputElement, "finance");
    });

    expect(element.textContent).toContain("Default Chat");
    expect(element.textContent).toContain("No matching agents");
    expect(element.textContent).not.toContain("No agent catalog available");
    expect(element.textContent).not.toContain("Operations Reviewer");
  });

  it("selects a filtered agent runner with ArrowDown and Enter", async () => {
    const onSelectAgent = vi.fn();
    const { element } = await renderComposer({ agentOptions: searchableAgents, onSelectAgent });
    const agentButton = element.querySelector('[aria-label="Agent runner: Default Chat"]');
    expect(agentButton).toBeInstanceOf(HTMLButtonElement);

    await act(async () => {
      (agentButton as HTMLButtonElement).click();
    });
    const searchInput = element.querySelector('[aria-label="Search agents"]');
    expect(searchInput).toBeInstanceOf(HTMLInputElement);

    await act(async () => {
      changeInputValue(searchInput as HTMLInputElement, "video");
      searchInput!.dispatchEvent(new KeyboardEvent("keydown", { bubbles: true, cancelable: true, key: "ArrowDown" }));
      searchInput!.dispatchEvent(new KeyboardEvent("keydown", { bubbles: true, cancelable: true, key: "Enter" }));
    });

    expect(onSelectAgent).toHaveBeenCalledWith("agent-type-social-video-content-strategist");
  });

  it("closes the agent selector with Escape and restores focus to the trigger", async () => {
    const { element } = await renderComposer({ agentOptions: searchableAgents });
    const agentButton = element.querySelector('[aria-label="Agent runner: Default Chat"]');
    expect(agentButton).toBeInstanceOf(HTMLButtonElement);
    const agentButtonElement = agentButton as HTMLButtonElement;

    await act(async () => {
      agentButtonElement.click();
    });
    const searchInput = element.querySelector('[aria-label="Search agents"]');
    expect(searchInput).toBeInstanceOf(HTMLInputElement);
    await act(async () => {
      changeInputValue(searchInput as HTMLInputElement, "ops");
      searchInput!.dispatchEvent(new KeyboardEvent("keydown", { bubbles: true, cancelable: true, key: "Escape" }));
    });

    expect(agentButtonElement.getAttribute("aria-expanded")).toBe("false");
    expect(element.querySelector('[aria-label="Search agents"]')).toBeNull();
    expect(document.activeElement).toBe(agentButtonElement);
  });

  it("does not select an agent runner while IME composition is confirming", async () => {
    const onSelectAgent = vi.fn();
    const { element } = await renderComposer({ onSelectAgent });
    const agentButton = element.querySelector('[aria-label="Agent runner: Default Chat"]');
    expect(agentButton).toBeInstanceOf(HTMLButtonElement);
    const agentButtonElement = agentButton as HTMLButtonElement;

    await act(async () => {
      agentButtonElement.click();
    });
    const searchInput = element.querySelector('[aria-label="Search agents"]');
    expect(searchInput).toBeInstanceOf(HTMLInputElement);
    const enterEvent = new KeyboardEvent("keydown", { bubbles: true, cancelable: true, key: "Enter" });
    Object.defineProperty(enterEvent, "isComposing", { value: true });

    await act(async () => {
      searchInput!.dispatchEvent(enterEvent);
    });

    expect(onSelectAgent).not.toHaveBeenCalled();
    expect(enterEvent.defaultPrevented).toBe(false);
    expect(agentButtonElement.getAttribute("aria-expanded")).toBe("true");
  });

  it("keeps the agent selector open after a mobile tap sequence", async () => {
    const { element } = await renderComposer();
    const agentButton = element.querySelector('[aria-label="Agent runner: Default Chat"]');
    expect(agentButton).toBeInstanceOf(HTMLButtonElement);

    await act(async () => {
      dispatchPointerDown(agentButton as HTMLButtonElement, "touch");
      (agentButton as HTMLButtonElement).click();
    });

    expect(agentButton?.getAttribute("aria-expanded")).toBe("true");
    expect(element.textContent).toContain("Social Video Content Strategist");
  });

  it("renders the execution mode badge as an icon-only control", async () => {
    const { element } = await renderComposer({ executionMode: "full-access" });

    const executionBadge = element.querySelector(".chatapp-execution-chip");
    const runtimeControls = element.querySelector(".chatapp-composer__runtime-badges");

    expect(executionBadge).toBeInstanceOf(HTMLSpanElement);
    expect(executionBadge?.getAttribute("aria-label")).toBe("Full access runtime");
    expect(executionBadge?.textContent).toContain("admin_panel_settings");
    expect(executionBadge?.textContent).not.toContain("full-access");
    expect(runtimeControls?.firstElementChild?.classList.contains("chatapp-provider-selector")).toBe(true);
    expect(runtimeControls?.lastElementChild).toBe(executionBadge);
  });

  it("places dictation next to the send action", async () => {
    const { element } = await renderComposer();

    const actions = element.querySelector(".chatapp-composer__actions");
    const dictation = element.querySelector(".chatapp-composer__dictation");
    const send = element.querySelector(".chatapp-composer__icon-action.is-send");

    expect(actions).toBeInstanceOf(HTMLDivElement);
    expect(dictation).toBeInstanceOf(HTMLDivElement);
    expect(send).toBeInstanceOf(HTMLButtonElement);
    expect(element.querySelector(".chatapp-composer__tools .chatapp-composer__dictation")).toBeNull();
    expect(Array.from(actions?.children || []).indexOf(dictation as Element)).toBeLessThan(
      Array.from(actions?.children || []).indexOf(send as Element),
    );
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
    const searchInput = element.querySelector('[aria-label="Search apps and references"]');
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
    expect(element.querySelector('[aria-label="Search apps and references"]')).toBeInstanceOf(HTMLInputElement);
    expect(element.textContent).toContain("@Checklist link in chat with @");
    expect(element.textContent).toContain("checklist · checklist · Operational checklist");
  });

  it("shows a skeleton while reference search is pending", async () => {
    vi.useFakeTimers();
    HTMLElement.prototype.scrollIntoView = vi.fn();
    const pendingSearch = deferred<MentionItem[]>();
    const onSearchReferences = vi.fn(() => pendingSearch.promise);
    const { element } = await renderComposer({ onSearchReferences });
    const pickerButton = element.querySelector('[aria-label="Apps and references"]');
    expect(pickerButton).toBeInstanceOf(HTMLButtonElement);

    await act(async () => {
      (pickerButton as HTMLButtonElement).click();
    });

    expect(element.querySelector('[aria-label="Searching references"]')).toBeInstanceOf(HTMLElement);
    expect(element.querySelectorAll(".chatapp-mention-panel__skeleton-row")).toHaveLength(1);
    expect(onSearchReferences).not.toHaveBeenCalled();

    await act(async () => {
      vi.advanceTimersByTime(180);
      await Promise.resolve();
    });

    expect(onSearchReferences).toHaveBeenCalledWith("", expect.any(AbortSignal));
    expect(element.querySelector('[aria-label="Searching references"]')).toBeInstanceOf(HTMLElement);

    await act(async () => {
      pendingSearch.resolve([checklistMention]);
      await Promise.resolve();
      await Promise.resolve();
    });

    expect(element.querySelector('[aria-label="Searching references"]')).toBeNull();
    expect(element.textContent).toContain("@Checklist link in chat with @");
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
    const searchInput = element.querySelector('[aria-label="Search apps and references"]');
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
      referenceButton!.dispatchEvent(new Event("pointerdown", { bubbles: true, cancelable: true }));
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
    const searchInput = element.querySelector('[aria-label="Search apps and references"]');
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
      referenceButton!.dispatchEvent(new Event("pointerdown", { bubbles: true, cancelable: true }));
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

  it("inserts dragged Checklist items as reference mentions", async () => {
    const onReferenceAdd = vi.fn();
    const { getValue } = await renderComposer({ onReferenceAdd });
    const dataTransfer = new FakeDataTransfer();
    dataTransfer.setData(
      "application/x-maverick-checklist",
      JSON.stringify({
        checked_count: 3,
        checklist_id: "check_drag123",
        deep_link: "/app/checklist/checklists/check_drag123",
        mode: "agent_plan",
        owner_app_id: "checklist",
        status: "active",
        summary: "Move checklist references into floating chat.",
        task_count: 5,
        title: "Checklist drag references",
      }),
    );

    await dropOnEditor(dataTransfer);

    expect(getValue()).toBe("@Checklist drag references [ref:checklist/checklist/check_drag123] ");
    expect(onReferenceAdd).toHaveBeenCalledWith({
      type: "entity",
      app_id: "checklist",
      entity_type: "checklist",
      entity_id: "check_drag123",
      label: "Checklist drag references",
      summary: "Move checklist references into floating chat.",
      deep_link: "/app/checklist/checklists/check_drag123",
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

  it("opens the multi-agent mode menu and selects a mode", async () => {
    const onSelectMultiAgentMode = vi.fn();
    const { element } = await renderComposer({ multiAgentMode: "off", onSelectMultiAgentMode });
    const trigger = element.querySelector('button[aria-label="Multi-agent mode: Off"]') as HTMLButtonElement | null;

    await act(async () => {
      trigger?.click();
    });

    expect(element.textContent).toContain("Auto");
    expect(element.textContent).not.toContain("Group chat");
    expect(element.textContent).toContain("1 worker · 1 turn · 1 tool call");

    const autoButton = [...element.querySelectorAll('[role="menuitemradio"]')].find((item) => item.textContent?.includes("Auto")) as HTMLButtonElement;
    await act(async () => {
      autoButton.click();
    });

    expect(onSelectMultiAgentMode).toHaveBeenCalledWith("auto");
  });

  it("shows group chat mode only when the feature flag is enabled", async () => {
    const onSelectMultiAgentMode = vi.fn();
    const { element } = await renderComposer({
      multiAgentGroupChatEnabled: true,
      multiAgentMode: "off",
      onSelectMultiAgentMode,
    });
    const trigger = element.querySelector('button[aria-label="Multi-agent mode: Off"]') as HTMLButtonElement | null;

    await act(async () => {
      trigger?.click();
    });

    expect(element.textContent).toContain("Group chat");
    const groupChatButton = [...element.querySelectorAll('[role="menuitemradio"]')].find((item) =>
      item.textContent?.includes("Group chat"),
    ) as HTMLButtonElement;
    await act(async () => {
      groupChatButton.click();
    });

    expect(onSelectMultiAgentMode).toHaveBeenCalledWith("group_chat");
  });
});
