// @vitest-environment happy-dom
import { act, useState } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { mailThreadDragPayloadFromThread, writeMailThreadDragData } from "../../../../mail/frontend/src/lib/mailThreadDragDrop";
import { appReferenceMentionItemsFromDataTransfer } from "../lib/storageDragReferences";
import type { ExternalMentionDrop } from "../lib/externalInputs";
import { useChatComposerContext } from "./useChatComposerContext";
import { useChatRootDropHandlers } from "./useChatRootDropHandlers";

vi.mock("../api/client", () => ({ listApps: vi.fn(async () => []) }));

function mailTransfer() {
  const values = new Map<string, string>();
  const transfer = {
    get types() { return [...values.keys()]; }, files: [], effectAllowed: "none", dropEffect: "none",
    setData: (type: string, value: string) => values.set(type, value),
    getData: (type: string) => values.get(type) || "",
  };
  writeMailThreadDragData(transfer as unknown as DataTransfer, mailThreadDragPayloadFromThread({
    id: "thread-fixture", connection_id: "fixture", subject: "Synthetic email", snippet: "Synthetic content",
    participants: [{ email: "sender@example.com" }], last_message_at: "2026-10-10T12:00:00Z",
    labels: ["inbox"], unread: true, starred: false,
  }));
  return transfer;
}

describe("Mail references dropped into Chat", () => {
  let container: HTMLDivElement;
  let root: Root;
  const addAttachments = vi.fn();
  function Harness({ ready = true, allowed = true, drop = null }: {
    ready?: boolean; allowed?: boolean; drop?: ExternalMentionDrop | null;
  }) {
    const [composer, setComposer] = useState("Existing text");
    const [error, setComposerError] = useState<string | null>(null);
    const context = useChatComposerContext({
      activeAppContext: null, appReferencesAllowed: allowed, addAttachments,
      externalFileDrop: null, externalMentionDrop: drop, navigationScope: "fixture", workspaceId: "default",
      ready, setComposer, setComposerError,
    });
    const handlers = useChatRootDropHandlers({
      disabled: !ready, handleAddAttachments: context.handleAddAttachments,
      handleAddReferenceMentions: context.appendMentionItemsToComposer,
    });
    return <main onDragOver={handlers.handleChatRootDragOver} onDrop={handlers.handleChatRootDrop}>
      <div data-testid="transcript">Transcript area</div><output>{composer}</output>
      <span data-testid="references">{JSON.stringify(context.selectedReferences)}</span>
      <span data-testid="error">{error}</span>
    </main>;
  }
  beforeEach(() => {
    vi.stubGlobal("IS_REACT_ACT_ENVIRONMENT", true);
    addAttachments.mockClear();
    container = document.createElement("div");
    document.body.append(container);
    root = createRoot(container);
  });
  afterEach(async () => {
    await act(async () => root.unmount());
    container.remove();
    vi.unstubAllGlobals();
  });
  async function dispatch(type: string, transfer: unknown) {
    const event = new Event(type, { bubbles: true, cancelable: true });
    Object.defineProperty(event, "dataTransfer", { value: transfer });
    await act(async () => container.querySelector('[data-testid="transcript"]')!.dispatchEvent(event));
    return event;
  }
  it("accepts Mail's actual drag payload on the transcript, retaining its structured reference", async () => {
    await act(async () => root.render(<Harness />));
    const transfer = mailTransfer();
    const bubbled = vi.fn();
    document.body.addEventListener("drop", bubbled);
    expect((await dispatch("dragover", transfer)).defaultPrevented).toBe(true);
    expect(transfer.dropEffect).toBe("copy");
    expect((await dispatch("drop", transfer)).defaultPrevented).toBe(true);
    document.body.removeEventListener("drop", bubbled);
    expect(container.querySelector("output")!.textContent).toContain("Existing text @Synthetic email");
    expect(JSON.parse(container.querySelector('[data-testid="references"]')!.textContent!)).toEqual([
      expect.objectContaining({ app_id: "mail", entity_type: "email_thread", entity_id: "thread-fixture", deep_link: "/app/mail?thread=thread-fixture" }),
    ]);
    expect(bubbled).not.toHaveBeenCalled();
    expect(addAttachments).not.toHaveBeenCalled();
  });
  it("waits for bootstrap before consuming a launcher/side-panel drop and inserts it once", async () => {
    const drop = { requestId: "drop-1", items: appReferenceMentionItemsFromDataTransfer(mailTransfer()) };
    await act(async () => root.render(<Harness ready={false} allowed={false} drop={drop} />));
    expect(container.querySelector("output")!.textContent).toBe("Existing text");
    expect(container.querySelector('[data-testid="error"]')!.textContent).toBe("");
    await act(async () => root.render(<Harness ready drop={drop} />));
    await act(async () => root.render(<Harness ready drop={{ ...drop }} />));
    expect(container.querySelector("output")!.textContent!.match(/@Synthetic email/g)).toHaveLength(1);
    expect(JSON.parse(container.querySelector('[data-testid="references"]')!.textContent!)).toHaveLength(1);
  });
  it("rejects references for profiles that do not allow them without changing the composer", async () => {
    await act(async () => root.render(<Harness allowed={false} />));
    await dispatch("drop", mailTransfer());
    expect(container.querySelector("output")!.textContent).toBe("Existing text");
    expect(container.querySelector('[data-testid="error"]')!.textContent).toContain("does not allow app references");
  });
  it("ignores malformed deep links and drops while the chat is disabled", async () => {
    await act(async () => root.render(<Harness />));
    const transfer = mailTransfer();
    const payload = JSON.parse(transfer.getData("application/x-loopino-mail-thread"));
    transfer.setData("application/x-loopino-mail-thread", JSON.stringify({ ...payload, deep_link: "https://external.example/" }));
    expect((await dispatch("drop", transfer)).defaultPrevented).toBe(false);
    await act(async () => root.render(<Harness ready={false} />));
    expect((await dispatch("drop", mailTransfer())).defaultPrevented).toBe(false);
    expect(container.querySelector("output")!.textContent).toBe("Existing text");
  });
  it("still accepts file attachments on the transcript", async () => {
    await act(async () => root.render(<Harness />));
    const file = new File(["fixture"], "fixture.txt", { type: "text/plain" });
    expect((await dispatch("drop", { types: ["Files"], files: [file] })).defaultPrevented).toBe(true);
    expect(addAttachments).toHaveBeenCalledWith([file]);
  });
});
