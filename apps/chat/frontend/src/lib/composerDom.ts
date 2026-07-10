import type { MentionToken } from "./mentions";
import { mentionText } from "./mentions";
import { mentionItemKindLabel } from "./referenceKindLabels";

type ComposerNode = ChildNode & {
  dataset?: {
    mentionText?: string;
  };
};

function isElementNode(node: ChildNode): node is HTMLElement {
  return node.nodeType === Node.ELEMENT_NODE;
}

function childNodes(node: Node): ComposerNode[] {
  return Array.from(node.childNodes) as ComposerNode[];
}

function nodeMentionText(node: ChildNode): string | null {
  return isElementNode(node) ? node.dataset.mentionText || null : null;
}

function textFromComposerNode(node: ChildNode): string {
  const tokenText = nodeMentionText(node);
  if (tokenText !== null) {
    return tokenText;
  }
  if (node.nodeType === Node.TEXT_NODE) {
    return node.textContent || "";
  }
  if (isElementNode(node) && node.tagName === "BR") {
    return "\n";
  }
  return childNodes(node)
    .map((child) => textFromComposerNode(child))
    .join("");
}

export function composerText(root: HTMLElement): string {
  return childNodes(root)
    .map((node) => textFromComposerNode(node))
    .join("");
}

function caretOffsetInNode(root: HTMLElement, target: Node, targetOffset: number): number {
  let offset = 0;
  let found = false;

  function visit(node: ChildNode): void {
    if (found) {
      return;
    }
    const tokenText = nodeMentionText(node);
    if (tokenText !== null) {
      if (node === target || node.contains(target)) {
        offset += tokenText.length;
        found = true;
        return;
      }
      offset += tokenText.length;
      return;
    }
    if (node.nodeType === Node.TEXT_NODE) {
      if (node === target) {
        offset += targetOffset;
        found = true;
        return;
      }
      offset += (node.textContent || "").length;
      return;
    }
    if (isElementNode(node) && node.tagName === "BR") {
      offset += 1;
      return;
    }
    const children = childNodes(node);
    if (node === target) {
      for (let index = 0; index < Math.min(targetOffset, children.length); index += 1) {
        offset += textFromComposerNode(children[index]).length;
      }
      found = true;
      return;
    }
    children.forEach(visit);
  }

  childNodes(root).forEach(visit);
  return offset;
}

export function composerCaretOffset(root: HTMLElement): number {
  const selection = window.getSelection();
  if (!selection || selection.rangeCount === 0 || !selection.anchorNode || !root.contains(selection.anchorNode)) {
    return composerText(root).length;
  }
  return caretOffsetInNode(root, selection.anchorNode, selection.anchorOffset);
}

export function composerSelectionOffsets(root: HTMLElement): { start: number; end: number } {
  const selection = window.getSelection();
  if (
    !selection ||
    selection.rangeCount === 0 ||
    !selection.anchorNode ||
    !selection.focusNode ||
    !root.contains(selection.anchorNode) ||
    !root.contains(selection.focusNode)
  ) {
    const end = composerText(root).length;
    return { start: end, end };
  }
  const anchor = caretOffsetInNode(root, selection.anchorNode, selection.anchorOffset);
  const focus = caretOffsetInNode(root, selection.focusNode, selection.focusOffset);
  return {
    start: Math.min(anchor, focus),
    end: Math.max(anchor, focus),
  };
}

function rangeAtComposerOffset(root: HTMLElement, offset: number): Range {
  const range = document.createRange();
  let remaining = Math.max(0, offset);
  let placed = false;

  function placeBefore(node: ChildNode) {
    range.setStartBefore(node);
    range.collapse(true);
    placed = true;
  }

  function placeAfter(node: ChildNode) {
    range.setStartAfter(node);
    range.collapse(true);
    placed = true;
  }

  function visit(node: ChildNode): void {
    if (placed) {
      return;
    }
    const tokenText = nodeMentionText(node);
    if (tokenText !== null) {
      if (remaining <= 0) {
        placeBefore(node);
        return;
      }
      if (remaining <= tokenText.length) {
        placeAfter(node);
        return;
      }
      remaining -= tokenText.length;
      return;
    }
    if (node.nodeType === Node.TEXT_NODE) {
      const textLength = (node.textContent || "").length;
      if (remaining <= textLength) {
        range.setStart(node, remaining);
        range.collapse(true);
        placed = true;
        return;
      }
      remaining -= textLength;
      return;
    }
    if (isElementNode(node) && node.tagName === "BR") {
      if (remaining <= 0) {
        placeBefore(node);
        return;
      }
      if (remaining <= 1) {
        placeAfter(node);
        return;
      }
      remaining -= 1;
      return;
    }
    childNodes(node).forEach(visit);
  }

  childNodes(root).forEach(visit);
  if (!placed) {
    range.selectNodeContents(root);
    range.collapse(false);
  }
  return range;
}

export function setComposerCaret(root: HTMLElement, offset: number): void {
  const range = rangeAtComposerOffset(root, offset);
  const selection = window.getSelection();
  selection?.removeAllRanges();
  selection?.addRange(range);
}

export function setComposerSelectionOffsets(root: HTMLElement, start: number, end: number): void {
  const selectionStart = Math.max(0, Math.min(start, end));
  const selectionEnd = Math.max(selectionStart, Math.max(start, end));
  const startRange = rangeAtComposerOffset(root, selectionStart);
  const endRange = rangeAtComposerOffset(root, selectionEnd);
  const range = document.createRange();
  range.setStart(startRange.startContainer, startRange.startOffset);
  range.setEnd(endRange.startContainer, endRange.startOffset);
  const selection = window.getSelection();
  selection?.removeAllRanges();
  selection?.addRange(range);
}

export function scrollComposerCaretIntoView(root: HTMLElement): void {
  const selection = window.getSelection();
  if (!selection || selection.rangeCount === 0 || !selection.anchorNode || !root.contains(selection.anchorNode)) {
    return;
  }
  const range = selection.getRangeAt(0);
  const rangeRect = range.getClientRects()[0] || range.getBoundingClientRect();
  const hasRangeRect = rangeRect && (rangeRect.top || rangeRect.bottom || rangeRect.height);
  if (!hasRangeRect) {
    if (composerCaretOffset(root) >= composerText(root).length) {
      root.scrollTop = root.scrollHeight;
    }
    return;
  }
  const rootRect = root.getBoundingClientRect();
  const padding = 8;
  if (rangeRect.top < rootRect.top + padding) {
    root.scrollTop = Math.max(0, root.scrollTop - (rootRect.top + padding - rangeRect.top));
    return;
  }
  if (rangeRect.bottom > rootRect.bottom - padding) {
    root.scrollTop += rangeRect.bottom - (rootRect.bottom - padding);
  }
}

function appendTextSegment(fragment: DocumentFragment, text: string): void {
  const parts = text.split("\n");
  parts.forEach((part, index) => {
    if (part) {
      fragment.append(document.createTextNode(part));
    }
    if (index < parts.length - 1) {
      fragment.append(document.createElement("br"));
    }
  });
}

function mentionChipElement(token: MentionToken, disabled: boolean, onRemove: (token: MentionToken) => void): HTMLElement {
  const chip = document.createElement("span");
  chip.className = `chatapp-mention-chip is-${token.item.kind}`;
  chip.contentEditable = "false";
  chip.dataset.mentionText = mentionText(token.item);

  const kind = document.createElement("span");
  kind.className = "chatapp-mention-chip__kind";
  kind.textContent = mentionItemKindLabel(token.item);

  const label = document.createElement("span");
  label.className = "chatapp-mention-chip__label";
  label.textContent = token.item.label;

  const remove = document.createElement("button");
  remove.type = "button";
  remove.className = "chatapp-mention-chip__remove";
  remove.setAttribute("aria-label", `Remove ${token.item.label}`);
  remove.disabled = disabled;
  remove.addEventListener("click", (event) => {
    event.preventDefault();
    onRemove(token);
  });

  const icon = document.createElement("span");
  icon.className = "material-symbols-rounded";
  icon.setAttribute("aria-hidden", "true");
  icon.textContent = "close";
  remove.append(icon);

  chip.append(kind, label, remove);
  return chip;
}

function mentionChipElements(root: HTMLElement): HTMLElement[] {
  return Array.from(root.querySelectorAll<HTMLElement>("[data-mention-text]"));
}

function composerContentIsCurrent(root: HTMLElement, text: string, tokens: MentionToken[], disabled: boolean): boolean {
  if (composerText(root) !== text) {
    return false;
  }
  const chips = mentionChipElements(root);
  if (chips.length !== tokens.length) {
    return false;
  }
  return tokens.every((token, index) => {
    const chip = chips[index];
    const removeButton = chip?.querySelector<HTMLButtonElement>(".chatapp-mention-chip__remove");
    return Boolean(
      chip &&
        chip.dataset.mentionText === mentionText(token.item) &&
        chip.classList.contains(`is-${token.item.kind}`) &&
        removeButton &&
        removeButton.disabled === disabled,
    );
  });
}

export function renderComposerContent(
  root: HTMLElement,
  text: string,
  tokens: MentionToken[],
  disabled: boolean,
  onRemove: (token: MentionToken) => void,
): boolean {
  if (composerContentIsCurrent(root, text, tokens, disabled)) {
    return false;
  }
  const fragment = document.createDocumentFragment();
  let cursor = 0;
  tokens.forEach((token) => {
    if (token.start > cursor) {
      appendTextSegment(fragment, text.slice(cursor, token.start));
    }
    fragment.append(mentionChipElement(token, disabled, onRemove));
    cursor = token.end;
  });
  if (cursor < text.length || !tokens.length) {
    appendTextSegment(fragment, text.slice(cursor));
  }
  root.replaceChildren(fragment);
  return true;
}

export function normalizePastedComposerText(text: string): string {
  return text.replace(/\r\n/g, "\n").replace(/\r/g, "\n");
}

export function isMobileComposerInput(): boolean {
  return (
    typeof window !== "undefined" &&
    typeof window.matchMedia === "function" &&
    (window.matchMedia("(pointer: coarse)").matches || window.matchMedia("(max-width: 720px)").matches)
  );
}
