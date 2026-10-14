/**
 * @vitest-environment happy-dom
 */
import { afterEach, describe, expect, it, vi } from "vitest";
import { composerCaretOffset, composerSelectionOffsets, composerText, renderComposerContent, setComposerCaret } from "./composerDom";

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

  it("keeps a terminal newline editable without counting its caret placeholder", () => {
    const root = composerRoot("First line\n");
    expect(root.querySelectorAll("br")).toHaveLength(2);
    expect(composerText(root)).toBe("First line\n");
    setComposerCaret(root, "First line\n".length);
    expect(composerCaretOffset(root)).toBe("First line\n".length);
    expect(renderComposerContent(root, "First line\n", [], false, vi.fn())).toBe(false);
    renderComposerContent(root, "First line\nSecond line", [], false, vi.fn());
    expect(root.querySelector("[data-composer-placeholder]")).toBeNull();
    expect(composerText(root)).toBe("First line\nSecond line");
  });
});
