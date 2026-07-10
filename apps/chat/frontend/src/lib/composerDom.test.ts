/**
 * @vitest-environment happy-dom
 */
import { afterEach, describe, expect, it, vi } from "vitest";
import { composerCaretOffset, composerSelectionOffsets, renderComposerContent } from "./composerDom";

function composerRoot(text: string): HTMLElement {
  const root = document.createElement("div");
  root.contentEditable = "true";
  document.body.append(root);
  renderComposerContent(root, text, [], false, vi.fn());
  return root;
}

function selectRootChildOffset(root: HTMLElement, offset: number) {
  const range = document.createRange();
  range.setStart(root, offset);
  range.collapse(true);
  const selection = window.getSelection();
  selection?.removeAllRanges();
  selection?.addRange(range);
}

describe("composerDom", () => {
  afterEach(() => {
    document.body.replaceChildren();
    window.getSelection()?.removeAllRanges();
  });

  it("maps root child selections between line breaks to composer text offsets", () => {
    const root = composerRoot("First sentence.\n\nSecond sentence");

    selectRootChildOffset(root, 2);

    const expectedOffset = "First sentence.\n".length;
    expect(composerCaretOffset(root)).toBe(expectedOffset);
    expect(composerSelectionOffsets(root)).toEqual({ start: expectedOffset, end: expectedOffset });
  });
});
