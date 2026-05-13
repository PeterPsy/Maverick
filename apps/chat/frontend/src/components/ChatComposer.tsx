import { ClipboardEvent, DragEvent, FormEvent, KeyboardEvent, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import type { Ref } from "react";
import type { AppReference, ProviderItem } from "../api/client";
import type { ComposerAttachment } from "../lib/attachments";
import { hasInvalidAttachments } from "../lib/attachments";
import { activeMentionAt, applyMention, filterMentionItems, findMentionTokens, mentionText, removeMentionToken } from "../lib/mentions";
import { referenceKey } from "../lib/mentions";
import type { MentionItem, MentionToken } from "../lib/mentions";
import { AttachmentMenu } from "./AttachmentMenu";
import { AttachmentPreviewStrip } from "./AttachmentPreviewStrip";
import { ProviderSelector } from "./ProviderSelector";

export type ExecutionMode = "sandbox" | "full-access";

type ComposerNode = ChildNode & {
  dataset?: {
    mentionText?: string;
  };
};

const REFERENCE_SEARCH_ERROR_MESSAGE = "Impossibile cercare app o record. Riprova o ricarica la pagina.";

function isAbortError(error: unknown): boolean {
  return Boolean(error && typeof error === "object" && "name" in error && error.name === "AbortError");
}

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

function composerText(root: HTMLElement): string {
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

function composerCaretOffset(root: HTMLElement): number {
  const selection = window.getSelection();
  if (!selection || selection.rangeCount === 0 || !selection.anchorNode || !root.contains(selection.anchorNode)) {
    return composerText(root).length;
  }
  return caretOffsetInNode(root, selection.anchorNode, selection.anchorOffset);
}

function setComposerCaret(root: HTMLElement, offset: number): void {
  const range = document.createRange();
  const selection = window.getSelection();
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
  selection?.removeAllRanges();
  selection?.addRange(range);
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
  kind.textContent = token.item.kind === "entity" ? "Record" : token.item.kind === "app" ? "App" : "Skill";

  const label = document.createElement("span");
  label.className = "chatapp-mention-chip__label";
  label.textContent = token.item.label;

  const remove = document.createElement("button");
  remove.type = "button";
  remove.className = "chatapp-mention-chip__remove";
  remove.setAttribute("aria-label", `Rimuovi ${token.item.label}`);
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

function renderComposerContent(root: HTMLElement, text: string, tokens: MentionToken[], disabled: boolean, onRemove: (token: MentionToken) => void): void {
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
}

function mentionItemKey(item: MentionItem): string {
  return item.reference ? referenceKey(item.reference) : `${item.kind}:${item.id}`;
}

function mergeMentionItems(...groups: MentionItem[][]): MentionItem[] {
  const seen = new Set<string>();
  const merged: MentionItem[] = [];
  for (const group of groups) {
    for (const item of group) {
      const key = mentionItemKey(item);
      if (seen.has(key)) {
        continue;
      }
      seen.add(key);
      merged.push(item);
    }
  }
  return merged;
}

export function ChatComposer({
  activeProviderId,
  attachments,
  canStopTurn,
  disabled,
  error,
  executionMode,
  isEmptyMode = false,
  isSending,
  mentionItems,
  onAddAttachments,
  onCapturePageArea,
  onChange,
  onReferenceAdd,
  onReferenceRemove,
  onSearchReferences,
  onSelectProvider,
  onRemoveAttachment,
  onStopTurn,
  onSubmit,
  providers,
  queuedCount,
  queuedPreview,
  value,
}: {
  activeProviderId: string;
  attachments: ComposerAttachment[];
  canStopTurn: boolean;
  disabled: boolean;
  error: string | null;
  executionMode: ExecutionMode | null;
  isEmptyMode?: boolean;
  isSending: boolean;
  mentionItems: MentionItem[];
  onAddAttachments: (files: File[]) => void;
  onCapturePageArea?: () => void;
  onChange: (value: string) => void;
  onReferenceAdd?: (reference: AppReference) => void;
  onReferenceRemove?: (reference: AppReference) => void;
  onSearchReferences?: (query: string, signal: AbortSignal) => Promise<MentionItem[]>;
  onSelectProvider: (providerId: string) => void;
  onRemoveAttachment: (attachmentId: string) => void;
  onStopTurn: () => void;
  onSubmit: () => void;
  providers: ProviderItem[];
  queuedCount: number;
  queuedPreview: string | null;
  value: string;
}) {
  const [isDraggingFiles, setIsDraggingFiles] = useState(false);
  const [caretIndex, setCaretIndex] = useState(value.length);
  const [dismissedMentionStart, setDismissedMentionStart] = useState<number | null>(null);
  const [selectedMentionIndex, setSelectedMentionIndex] = useState(0);
  const [showAppPicker, setShowAppPicker] = useState(false);
  const [selectedAppIndex, setSelectedAppIndex] = useState(0);
  const [referenceMentionItems, setReferenceMentionItems] = useState<MentionItem[]>([]);
  const [referenceSearchError, setReferenceSearchError] = useState<string | null>(null);
  const [appPickerQuery, setAppPickerQuery] = useState("");
  const [appPickerReferenceItems, setAppPickerReferenceItems] = useState<MentionItem[]>([]);
  const [appPickerSearchError, setAppPickerSearchError] = useState<string | null>(null);
  const editorRef = useRef<HTMLDivElement | null>(null);
  const appPickerButtonRef = useRef<HTMLButtonElement | null>(null);
  const appPickerPanelRef = useRef<HTMLDivElement | null>(null);
  const appPickerSearchRef = useRef<HTMLInputElement | null>(null);
  const pendingCaretIndexRef = useRef<number | null>(null);
  const searchableMentionItems = useMemo(
    () => mergeMentionItems(mentionItems, referenceMentionItems, appPickerReferenceItems),
    [appPickerReferenceItems, mentionItems, referenceMentionItems],
  );
  const mentionTokens = useMemo(() => findMentionTokens(value, searchableMentionItems), [searchableMentionItems, value]);
  const appPickerItems = useMemo(() => {
    const matchingApps = filterMentionItems(
      searchableMentionItems.filter((item) => item.kind === "app"),
      appPickerQuery,
    );
    const matchingReferences = filterMentionItems(appPickerReferenceItems, appPickerQuery);
    return mergeMentionItems(matchingApps, matchingReferences);
  }, [appPickerQuery, appPickerReferenceItems, searchableMentionItems]);
  const activeMentionCandidate = useMemo(() => activeMentionAt(value, caretIndex), [caretIndex, value]);
  const activeMentionComplete = activeMentionCandidate
    ? mentionTokens.some((token) => token.start === activeMentionCandidate.start && caretIndex >= token.end)
    : false;
  const activeMention = activeMentionCandidate?.start === dismissedMentionStart || activeMentionComplete ? null : activeMentionCandidate;
  const filteredMentionItems = useMemo(() => {
    if (!activeMention) {
      return [];
    }
    return filterMentionItems(
      searchableMentionItems.filter((item) => item.kind === activeMention.kind || (activeMention.kind === "app" && item.kind === "entity")),
      activeMention.query,
    );
  }, [activeMention, searchableMentionItems]);
  const isMentionPanelOpen = Boolean(activeMention);

  useLayoutEffect(() => {
    const editor = editorRef.current;
    if (!editor) {
      return;
    }
    const wasFocused = document.activeElement === editor;
    const nextCaretIndex = pendingCaretIndexRef.current ?? Math.min(caretIndex, value.length);
    pendingCaretIndexRef.current = null;
    renderComposerContent(editor, value, mentionTokens, disabled, removeMention);
    if (wasFocused) {
      setComposerCaret(editor, nextCaretIndex);
    }
  }, [caretIndex, disabled, mentionTokens, value]);

  useEffect(() => {
    setSelectedMentionIndex(0);
  }, [activeMention?.kind, activeMention?.query]);

  useEffect(() => {
    if (!activeMention || activeMention.kind !== "app" || !onSearchReferences) {
      setReferenceMentionItems([]);
      setReferenceSearchError(null);
      return;
    }
    setReferenceSearchError(null);
    const controller = new AbortController();
    const timer = window.setTimeout(() => {
      onSearchReferences(activeMention.query, controller.signal)
        .then((items) => {
          setReferenceMentionItems(items);
          setReferenceSearchError(null);
        })
        .catch((error) => {
          if (!isAbortError(error)) {
            setReferenceMentionItems([]);
            setReferenceSearchError(REFERENCE_SEARCH_ERROR_MESSAGE);
          }
        });
    }, 160);
    return () => {
      window.clearTimeout(timer);
      controller.abort();
    };
  }, [activeMention?.kind, activeMention?.query, onSearchReferences]);

  useEffect(() => {
    if (!showAppPicker || !onSearchReferences) {
      if (!showAppPicker) {
        setAppPickerSearchError(null);
      }
      return;
    }
    const query = appPickerQuery.trim();
    setAppPickerSearchError(null);
    const controller = new AbortController();
    const timer = window.setTimeout(() => {
      onSearchReferences(query, controller.signal)
        .then((items) => {
          setAppPickerReferenceItems(items);
          setAppPickerSearchError(null);
        })
        .catch((error) => {
          if (!isAbortError(error)) {
            setAppPickerReferenceItems([]);
            setAppPickerSearchError(REFERENCE_SEARCH_ERROR_MESSAGE);
          }
        });
    }, 160);
    return () => {
      window.clearTimeout(timer);
      controller.abort();
    };
  }, [appPickerQuery, onSearchReferences, showAppPicker]);

  useEffect(() => {
    setSelectedAppIndex(0);
  }, [appPickerItems]);

  useEffect(() => {
    if (showAppPicker) {
      appPickerSearchRef.current?.focus();
    }
  }, [showAppPicker]);

  useEffect(() => {
    if (!showAppPicker) {
      return;
    }
    const handlePointerDown = (event: PointerEvent) => {
      const target = event.target as Node | null;
      if (!target || appPickerPanelRef.current?.contains(target) || appPickerButtonRef.current?.contains(target)) {
        return;
      }
      setShowAppPicker(false);
    };
    document.addEventListener("pointerdown", handlePointerDown);
    return () => document.removeEventListener("pointerdown", handlePointerDown);
  }, [showAppPicker]);

  useEffect(() => {
    if (dismissedMentionStart === null) {
      return;
    }
    const dismissedTrigger = value[dismissedMentionStart];
    if (dismissedTrigger !== "@" && dismissedTrigger !== "$") {
      setDismissedMentionStart(null);
    }
  }, [dismissedMentionStart, value]);

  function submit(event: FormEvent) {
    event.preventDefault();
    onSubmit();
  }

  function syncCaret(editor: HTMLDivElement) {
    setCaretIndex(composerCaretOffset(editor));
  }

  function updateComposerFromEditor(editor: HTMLDivElement) {
    const nextValue = composerText(editor);
    const nextCaret = composerCaretOffset(editor);
    pendingCaretIndexRef.current = nextCaret;
    onChange(nextValue);
    setCaretIndex(nextCaret);
  }

  function insertMention(item: MentionItem) {
    if (!activeMention) {
      return;
    }
    const next = applyMention(value, activeMention, item);
    pendingCaretIndexRef.current = next.cursor;
    onChange(next.value);
    if (item.reference) {
      onReferenceAdd?.(item.reference);
    }
    setCaretIndex(next.cursor);
    setDismissedMentionStart(activeMention.start);
    requestAnimationFrame(() => {
      const editor = editorRef.current;
      if (!editor) {
        return;
      }
      editor.focus();
      setComposerCaret(editor, next.cursor);
    });
  }

  function removeMention(token: MentionToken) {
    const next = removeMentionToken(value, token);
    pendingCaretIndexRef.current = next.cursor;
    onChange(next.value);
    if (token.item.reference) {
      onReferenceRemove?.(token.item.reference);
    }
    setCaretIndex(next.cursor);
    requestAnimationFrame(() => {
      const editor = editorRef.current;
      if (!editor) {
        return;
      }
      editor.focus();
      setComposerCaret(editor, next.cursor);
    });
  }

  function insertAppMention(item: MentionItem) {
    const boundedCaret = Math.max(0, Math.min(caretIndex, value.length));
    const before = value.slice(0, boundedCaret);
    const after = value.slice(boundedCaret);
    const prefix = before && !/\s$/.test(before) ? " " : "";
    const suffix = after && /^\s/.test(after) ? "" : " ";
    const insertion = `${prefix}${mentionText(item)}${suffix}`;
    const nextValue = `${before}${insertion}${after}`;
    const nextCaret = before.length + insertion.length;
    pendingCaretIndexRef.current = nextCaret;
    onChange(nextValue);
    if (item.reference) {
      onReferenceAdd?.(item.reference);
    }
    setCaretIndex(nextCaret);
    setDismissedMentionStart(null);
    setShowAppPicker(false);
    setAppPickerQuery("");
    setAppPickerSearchError(null);
    requestAnimationFrame(() => {
      const editor = editorRef.current;
      if (!editor) {
        return;
      }
      editor.focus();
      setComposerCaret(editor, nextCaret);
    });
  }

  function onComposerKeyDown(event: KeyboardEvent<HTMLDivElement>) {
    if (showAppPicker && !isMentionPanelOpen) {
      if (event.key === "Escape") {
        event.preventDefault();
        setShowAppPicker(false);
        return;
      }
      if (appPickerItems.length) {
        if (event.key === "ArrowDown") {
          event.preventDefault();
          setSelectedAppIndex((current) => (current + 1) % appPickerItems.length);
          return;
        }
        if (event.key === "ArrowUp") {
          event.preventDefault();
          setSelectedAppIndex((current) => (current - 1 + appPickerItems.length) % appPickerItems.length);
          return;
        }
        if (event.key === "Tab" || event.key === "Enter") {
          event.preventDefault();
          insertAppMention(appPickerItems[selectedAppIndex] || appPickerItems[0]);
          return;
        }
      }
    }
    if (isMentionPanelOpen) {
      if (event.key === "Escape") {
        event.preventDefault();
        setDismissedMentionStart(activeMention?.start ?? null);
        return;
      }
      if (filteredMentionItems.length) {
        if (event.key === "ArrowDown") {
          event.preventDefault();
          setSelectedMentionIndex((current) => (current + 1) % filteredMentionItems.length);
          return;
        }
        if (event.key === "ArrowUp") {
          event.preventDefault();
          setSelectedMentionIndex((current) => (current - 1 + filteredMentionItems.length) % filteredMentionItems.length);
          return;
        }
        if (event.key === "Enter" || event.key === "Tab") {
          event.preventDefault();
          insertMention(filteredMentionItems[selectedMentionIndex] || filteredMentionItems[0]);
          return;
        }
      }
    }
    if (event.key === "Enter" && !event.shiftKey && !event.altKey) {
      event.preventDefault();
      onSubmit();
    }
  }

  function onAppPickerSearchKeyDown(event: KeyboardEvent<HTMLInputElement>) {
    if (event.key === "Escape") {
      event.preventDefault();
      setShowAppPicker(false);
      editorRef.current?.focus();
      return;
    }
    if (!appPickerItems.length) {
      return;
    }
    if (event.key === "ArrowDown") {
      event.preventDefault();
      setSelectedAppIndex((current) => (current + 1) % appPickerItems.length);
      return;
    }
    if (event.key === "ArrowUp") {
      event.preventDefault();
      setSelectedAppIndex((current) => (current - 1 + appPickerItems.length) % appPickerItems.length);
      return;
    }
    if (event.key === "Tab" || event.key === "Enter") {
      event.preventDefault();
      insertAppMention(appPickerItems[selectedAppIndex] || appPickerItems[0]);
    }
  }

  function onDragOver(event: DragEvent<HTMLDivElement>) {
    if (!event.dataTransfer.types.includes("Files")) {
      return;
    }
    event.preventDefault();
    setIsDraggingFiles(true);
  }

  function onDrop(event: DragEvent<HTMLDivElement>) {
    if (!event.dataTransfer.files.length) {
      return;
    }
    event.preventDefault();
    setIsDraggingFiles(false);
    onAddAttachments(Array.from(event.dataTransfer.files));
  }

  function onPaste(event: ClipboardEvent<HTMLDivElement>) {
    if (disabled || !event.clipboardData.files.length) {
      return;
    }
    event.preventDefault();
    event.stopPropagation();
    onAddAttachments(Array.from(event.clipboardData.files));
  }

  return (
    <>
      <section className={`chat-ui-surface chatapp-composer ${isEmptyMode ? "is-empty-mode" : "is-docked"}`}>
        {isDraggingFiles ? <DropOverlay /> : null}
        <form className="chatapp-form-stack" onSubmit={submit}>
          <AttachmentPreviewStrip attachments={attachments} disabled={isSending} onRemoveAttachment={onRemoveAttachment} />
          <QueuedMessageNotice queuedCount={queuedCount} queuedPreview={queuedPreview} />
          <div className={`chatapp-composer__input-shell ${showAppPicker ? "has-app-picker" : ""}`}>
            {showAppPicker ? (
              <MentionPanel
                activeIndex={Math.min(selectedAppIndex, Math.max(appPickerItems.length - 1, 0))}
                className="chatapp-mention-panel--app-picker"
                items={appPickerItems}
                kind="app"
                onSelect={insertAppMention}
                onSearchKeyDown={onAppPickerSearchKeyDown}
                onSearchQueryChange={setAppPickerQuery}
                query=""
                searchInputRef={appPickerSearchRef}
                searchPlaceholder="Cerca app o checklist"
                searchQuery={appPickerQuery}
                statusMessage={appPickerSearchError}
                ref={appPickerPanelRef}
              />
            ) : null}
            <div className={`chatapp-composer__text-area ${isSending ? "is-busy" : "is-idle"}`}>
              <div
                aria-disabled={disabled}
                className={`chat-ui-input chat-ui-input--textarea chatapp-composer__field chatapp-composer__editor ${value ? "" : "is-empty"}`}
                contentEditable={!disabled}
                data-placeholder="Scrivi a Maverick..."
                onClick={(event) => syncCaret(event.currentTarget)}
                onDragLeave={() => setIsDraggingFiles(false)}
                onDragOver={onDragOver}
                onDrop={onDrop}
                onInput={(event) => updateComposerFromEditor(event.currentTarget)}
                onKeyDown={onComposerKeyDown}
                onKeyUp={(event) => syncCaret(event.currentTarget)}
                onMouseUp={(event) => syncCaret(event.currentTarget)}
                onPaste={onPaste}
                ref={editorRef}
                role="textbox"
                suppressContentEditableWarning
                tabIndex={disabled ? -1 : 0}
              />
              {activeMention ? (
                <MentionPanel
                  activeIndex={Math.min(selectedMentionIndex, Math.max(filteredMentionItems.length - 1, 0))}
                  items={filteredMentionItems}
                  kind={activeMention.kind}
                  onSelect={insertMention}
                  query={activeMention.query}
                  statusMessage={referenceSearchError}
                />
              ) : null}
            </div>
            <div className="chatapp-composer__toolbar">
              <div className="chatapp-composer__tools">
                <AttachmentMenu attachments={attachments} disabled={disabled} onAddAttachments={onAddAttachments} onCapturePageArea={onCapturePageArea} />
                <button
                  aria-expanded={showAppPicker}
                  aria-haspopup="listbox"
                  aria-label="App citabili"
                  className={`chatapp-composer__tool-button ${showAppPicker ? "is-active" : ""}`}
                  disabled={disabled}
                  onClick={() => {
                    setShowAppPicker((current) => {
                      const next = !current;
                      if (next) {
                        setAppPickerQuery("");
                        setAppPickerSearchError(null);
                      }
                      return next;
                    });
                  }}
                  ref={appPickerButtonRef}
                  type="button"
                >
                  <span aria-hidden="true" className="material-symbols-rounded">
                    apps
                  </span>
                </button>
                <ComposerRuntimeBadges
                  activeProviderId={activeProviderId}
                  disabled={disabled || isSending}
                  executionMode={executionMode}
                  onSelectProvider={onSelectProvider}
                  providers={providers}
                />
              </div>
              <ComposerActions
                canSend={!disabled && !hasInvalidAttachments(attachments) && Boolean(value.trim() || attachments.length)}
                canStopTurn={canStopTurn}
                isSending={isSending}
                onStopTurn={onStopTurn}
                onSubmit={onSubmit}
              />
            </div>
          </div>
          {error ? <div className="chat-ui-field__message chat-ui-field__message--error chatapp-composer__error">{error}</div> : null}
        </form>
      </section>
    </>
  );
}

function ComposerRuntimeBadges({
  activeProviderId,
  disabled,
  executionMode,
  onSelectProvider,
  providers,
}: {
  activeProviderId: string;
  disabled: boolean;
  executionMode: ExecutionMode | null;
  onSelectProvider: (providerId: string) => void;
  providers: ProviderItem[];
}) {
  return (
    <div className="chatapp-composer__runtime-badges">
      <ProviderSelector activeProviderId={activeProviderId} disabled={disabled} onSelect={onSelectProvider} providers={providers} />
      {executionMode ? (
        <span className={`chatapp-execution-chip ${executionMode === "full-access" ? "is-full-access" : "is-sandbox"}`}>
          <span aria-hidden="true" className="material-symbols-rounded">
            {executionMode === "full-access" ? "admin_panel_settings" : "lock"}
          </span>
          {executionMode}
        </span>
      ) : null}
    </div>
  );
}

function MentionPanel({
  activeIndex,
  className = "",
  items,
  kind,
  onSelect,
  onSearchKeyDown,
  onSearchQueryChange,
  query,
  ref,
  searchInputRef,
  searchPlaceholder,
  searchQuery,
  statusMessage,
}: {
  activeIndex: number;
  className?: string;
  items: MentionItem[];
  kind: "app" | "skill";
  onSelect: (item: MentionItem) => void;
  onSearchKeyDown?: (event: KeyboardEvent<HTMLInputElement>) => void;
  onSearchQueryChange?: (query: string) => void;
  query: string;
  ref?: Ref<HTMLDivElement>;
  searchInputRef?: Ref<HTMLInputElement>;
  searchPlaceholder?: string;
  searchQuery?: string;
  statusMessage?: string | null;
}) {
  const activeItemRef = useRef<HTMLButtonElement | null>(null);

  useEffect(() => {
    activeItemRef.current?.scrollIntoView({ block: "nearest" });
  }, [activeIndex]);

  return (
    <div className={`chatapp-mention-panel ${className}`} ref={ref} role="listbox" aria-label={kind === "app" ? "Suggerimenti app e record" : "Suggerimenti skill"}>
      <div className="chatapp-mention-panel__header">{kind === "app" ? "App e record" : "Skill"}</div>
      {onSearchQueryChange ? (
        <label className="chatapp-mention-panel__search">
          <span className="chatapp-mention-panel__search-label">Cerca</span>
          <input
            aria-label="Cerca app o record"
            className="chatapp-mention-panel__search-input"
            onChange={(event) => onSearchQueryChange(event.currentTarget.value)}
            onKeyDown={onSearchKeyDown}
            placeholder={searchPlaceholder || "Cerca"}
            ref={searchInputRef}
            type="search"
            value={searchQuery || ""}
          />
        </label>
      ) : null}
      {statusMessage ? (
        <div className="chatapp-mention-panel__error" role="status">
          {statusMessage}
        </div>
      ) : null}
      {items.length ? (
        items.map((item, index) => (
          <button
            aria-selected={index === activeIndex}
            className={`chatapp-mention-panel__item ${index === activeIndex ? "is-active" : ""}`}
            key={`${item.kind}:${item.id}`}
            onMouseDown={(event) => {
              event.preventDefault();
              onSelect(item);
            }}
            ref={index === activeIndex ? activeItemRef : null}
            role="option"
            type="button"
          >
            <span className="chatapp-mention-panel__name">
              {item.kind === "skill" ? "$" : "@"}
              {item.label}
            </span>
            {item.description ? <span className="chatapp-mention-panel__description">{item.description}</span> : null}
          </button>
        ))
      ) : statusMessage ? null : (
        <div className="chatapp-mention-panel__empty">Nessun risultato per {query.trim() || "questo riferimento"}</div>
      )}
    </div>
  );
}

function ComposerActions({
  canSend,
  canStopTurn,
  isSending,
  onStopTurn,
  onSubmit,
}: {
  canSend: boolean;
  canStopTurn: boolean;
  isSending: boolean;
  onStopTurn: () => void;
  onSubmit: () => void;
}) {
  return (
    <div className="chatapp-composer__actions">
      {canStopTurn ? (
        <button aria-label="Stop chat" className="chatapp-composer__icon-action is-stop" onClick={onStopTurn} title="Stop chat" type="button">
          <span aria-hidden="true" className="material-symbols-rounded">
            stop_circle
          </span>
          <span className="chatapp-composer__stop-label">Stop chat</span>
        </button>
      ) : null}
      <button
        aria-label={isSending ? "Metti in coda il messaggio" : "Invia messaggio"}
        className="chatapp-composer__icon-action is-send"
        disabled={!canSend}
        onClick={onSubmit}
        title={isSending ? "Metti in coda" : "Invia"}
        type="button"
      >
        <span aria-hidden="true" className="material-symbols-rounded">
          send
        </span>
        <span className="chatapp-composer__send-label">Invia</span>
      </button>
    </div>
  );
}

function DropOverlay() {
  return (
    <div className="chatapp-chat-dropzone" aria-hidden="true">
      <div className="chatapp-chat-dropzone__content">
        <span className="chatapp-chat-dropzone__icon">
          <span className="material-symbols-rounded" aria-hidden="true">
            add
          </span>
        </span>
        <span>Rilascia il tuo file qui per allegarlo in chat</span>
      </div>
    </div>
  );
}

function QueuedMessageNotice({ queuedCount, queuedPreview }: { queuedCount: number; queuedPreview: string | null }) {
  if (queuedCount === 0) {
    return null;
  }
  return (
    <div className="chatapp-composer-queue" aria-live="polite">
      <div className="chatapp-composer-queue__eyebrow">
        <strong>{queuedCount} messaggi in coda</strong>
        <span>Invio automatico dopo il turn attivo</span>
      </div>
      {queuedPreview ? <div className="chatapp-composer-queue__preview">{queuedPreview}</div> : null}
    </div>
  );
}
