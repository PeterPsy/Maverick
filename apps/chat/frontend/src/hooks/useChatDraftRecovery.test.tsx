// @vitest-environment happy-dom
import { act, useState } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { useChatDraftRecovery } from "./useChatDraftRecovery";
import { composerDraftKey, composerDraftStorage, readComposerDraft, writeComposerDraft } from "../lib/composerDrafts";

const roots: Root[] = [];
Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
beforeEach(() => {
  localStorage.clear();
  vi.spyOn(window.location, "hostname", "get").mockReturnValue("af-0123456789abcdef01234567.sidecars.loopino.test");
});
afterEach(() => {
  roots.splice(0).forEach(root => act(() => root.unmount()));
  vi.restoreAllMocks();
  localStorage.clear();
  document.body.replaceChildren();
});

async function mount(conversationKey = "thread:a", navigationScope = "", workspaceId = "default", ready = true) {
  let edit!: (text: string) => void;
  let text = "";
  let target!: (key: string) => void;
  const container = document.createElement("div");
  document.body.append(container);
  const root = createRoot(container);
  roots.push(root);
  function Harness() {
    const [composer, setComposer] = useState("");
    const [conversation, setConversation] = useState(conversationKey);
    edit = setComposer;
    target = key => { setComposer(""); setConversation(key); };
    text = composer;
    useChatDraftRecovery({ ready, workspaceId, navigationScope, conversationKey: conversation, composer, setComposer });
    return <textarea value={composer} onChange={event => setComposer(event.target.value)} />;
  }
  await act(async () => root.render(<Harness />));
  return { edit, target, text: () => text, unmount: () => act(() => root.unmount()) };
}

it("restores the latest unsent text after the controller and document memory are discarded", async () => {
  const first = await mount();
  await act(async () => first.edit(" Prima riga\nSeconda riga "));
  document.dispatchEvent(new Event("visibilitychange"));
  first.unmount();
  const recovered = await mount();
  expect(recovered.text()).toBe(" Prima riga\nSeconda riga ");
});

it("keeps drafts in their conversation, workspace and floating window", async () => {
  const first = await mount();
  await act(async () => first.edit("draft A"));
  await act(async () => first.target("thread:b"));
  expect(first.text()).toBe("");
  await act(async () => first.edit("draft B"));
  await act(async () => first.target("thread:a"));
  expect(first.text()).toBe("draft A");
  expect((await mount("thread:a", "window-b")).text()).toBe("");
  expect((await mount("thread:a", "", "other")).text()).toBe("");
});

it("does not resurrect text after it was cleared or submitted", async () => {
  const first = await mount();
  await act(async () => first.edit("send me"));
  await act(async () => first.edit(""));
  first.unmount();
  expect((await mount()).text()).toBe("");
});

it("treats an empty rich editor's whitespace as a cleared draft", async () => {
  const first = await mount();
  await act(async () => first.edit("draft"));
  await act(async () => first.edit("\n"));
  first.unmount();
  expect((await mount()).text()).toBe("");
});

it("waits for live initialization and excludes shared platform origins", async () => {
  const key = composerDraftKey("default", "", "thread:a");
  writeComposerDraft(localStorage, key, "private draft");
  expect((await mount("thread:a", "", "default", false)).text()).toBe("");
  vi.spyOn(window.location, "hostname", "get").mockReturnValue("loopino.test");
  expect(composerDraftStorage()).toBeNull();
  expect((await mount()).text()).toBe("");
});

it("expires old text, rejects malformed records and bounds storage without touching other data", () => {
  const now = 100_000_000;
  const key = composerDraftKey("default", "", "thread:a");
  localStorage.setItem("unrelated", "keep");
  writeComposerDraft(localStorage, key, "expired", now - 86_400_001);
  expect(readComposerDraft(localStorage, key, now)).toBeNull();
  localStorage.setItem(key, "{broken");
  expect(readComposerDraft(localStorage, key, now)).toBeNull();
  expect(localStorage.getItem(key)).toBeNull();
  for (let index = 0; index < 25; index++) {
    writeComposerDraft(localStorage, composerDraftKey("default", "", `thread:${index}`), `draft ${index}`, now + index);
  }
  expect(localStorage.length).toBe(21);
  expect(localStorage.getItem("unrelated")).toBe("keep");
  expect(readComposerDraft(localStorage, composerDraftKey("default", "", "thread:24"), now + 25)).toBe("draft 24");
  writeComposerDraft(localStorage, key, "x".repeat(65_537), now + 26);
  expect(localStorage.getItem(key)).toBeNull();
});

it("keeps typing usable when browser persistence is denied", async () => {
  vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => { throw new Error("denied"); });
  const composer = await mount();
  await act(async () => composer.edit("still editable"));
  expect(composer.text()).toBe("still editable");
});
