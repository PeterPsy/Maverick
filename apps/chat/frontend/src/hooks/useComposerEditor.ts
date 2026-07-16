import {
  type ClipboardEvent,
  type Dispatch,
  type DragEvent,
  type KeyboardEvent,
  type RefObject,
  type SetStateAction,
  useLayoutEffect,
  useRef,
  useState,
} from "react";
import {
  composerCaretOffset,
  composerSelectionOffsets,
  composerText,
  isMobileComposerInput,
  normalizePastedComposerText,
  renderComposerContent,
  scrollComposerCaretIntoView,
  setComposerSelectionOffsets,
} from "../lib/composerDom";
import type { MentionItem, MentionToken } from "../lib/mentions";
import { appReferenceMentionItemsFromDataTransfer, hasAppReferenceDragData } from "../lib/storageDragReferences";

type UseComposerEditorParams = {
  caretIndex: number;
  clearDismissedMention: () => void;
  disabled: boolean;
  editorRef: RefObject<HTMLDivElement | null>;
  filteredMentionItems: MentionItem[];
  handleAppMentionPickerKey: (event: KeyboardEvent<HTMLElement>, focusEditorOnClose?: boolean) => boolean;
  insertAppMentions: (items: MentionItem[]) => void;
  insertMention: (item: MentionItem) => void;
  isSkillMentionPanelOpen: boolean;
  mentionTokens: MentionToken[];
  onAddAttachments: (files: File[]) => void;
  onChange: (value: string) => void;
  onRemoveMention: (token: MentionToken) => void;
  onSubmit: () => void;
  pendingCaretIndexRef: RefObject<number | null>;
  selectedMentionIndex: number;
  setCaretIndex: Dispatch<SetStateAction<number>>;
  setDismissedSkillMention: () => void;
  setSelectedMentionIndex: Dispatch<SetStateAction<number>>;
  value: string;
};

type DictationCommand = {
  text?: string;
  type?: string;
};

type ComposerEditKind = "dictation" | "dictation-command" | "external" | "history" | "newline" | "paste" | "programmatic" | "typing";

type ComposerSelection = {
  end: number;
  start: number;
};

type ComposerHistorySnapshot = ComposerSelection & {
  kind: ComposerEditKind;
  timestamp: number;
  value: string;
};

type ComposerHistoryState = {
  current: ComposerHistorySnapshot;
  redo: ComposerHistorySnapshot[];
  undo: ComposerHistorySnapshot[];
};

const COMPOSER_HISTORY_LIMIT = 100;
const TYPING_COALESCE_MS = 1_000;

export function useComposerEditor({
  caretIndex,
  clearDismissedMention,
  disabled,
  editorRef,
  filteredMentionItems,
  handleAppMentionPickerKey,
  insertAppMentions,
  insertMention,
  isSkillMentionPanelOpen,
  mentionTokens,
  onAddAttachments,
  onChange,
  onRemoveMention,
  onSubmit,
  pendingCaretIndexRef,
  selectedMentionIndex,
  setCaretIndex,
  setDismissedSkillMention,
  setSelectedMentionIndex,
  value,
}: UseComposerEditorParams) {
  const [dictationError, setDictationError] = useState<string | null>(null);
  const historyRef = useRef<ComposerHistoryState>({
    current: composerHistorySnapshot(value, collapsedComposerSelection(value, caretIndex), "external"),
    redo: [],
    undo: [],
  });
  const pendingSelectionRef = useRef<ComposerSelection | null>(null);
  const pendingSelectionRestoreRef = useRef(false);

  useLayoutEffect(() => {
    const editor = editorRef.current;
    if (!editor) {
      return;
    }
    const wasFocused = document.activeElement === editor;
    const pendingCaretIndex = pendingCaretIndexRef.current;
    const pendingSelection = pendingSelectionRef.current;
    const shouldRestorePendingSelection = pendingSelectionRestoreRef.current;
    const nextSelection = pendingSelection ?? collapsedComposerSelection(value, pendingCaretIndex ?? Math.min(caretIndex, value.length));
    let forceSelectionRestore = shouldRestorePendingSelection;

    if (historyRef.current.current.value !== value) {
      if (pendingCaretIndex !== null) {
        recordComposerChange(value, nextSelection, "programmatic");
        forceSelectionRestore = true;
      } else {
        resetComposerHistory(value, nextSelection);
      }
    } else {
      updateCurrentHistorySelection(nextSelection);
    }

    pendingCaretIndexRef.current = null;
    pendingSelectionRef.current = null;
    pendingSelectionRestoreRef.current = false;
    const didRender = renderComposerContent(editor, value, mentionTokens, disabled, onRemoveMention);
    if (wasFocused && (didRender || forceSelectionRestore)) {
      setComposerSelectionOffsets(editor, nextSelection.start, nextSelection.end);
      scrollComposerCaretIntoView(editor);
    }
  }, [disabled, mentionTokens, value]);

  function syncCaret(editor: HTMLDivElement) {
    updateCurrentHistorySelection(composerSelectionOffsets(editor));
    setCaretIndex(composerCaretOffset(editor));
  }

  function updateComposerFromEditor(editor: HTMLDivElement) {
    const nextValue = composerText(editor);
    const nextCaret = composerCaretOffset(editor);
    const nextSelection = composerSelectionOffsets(editor);
    pendingCaretIndexRef.current = nextCaret;
    recordComposerChange(nextValue, nextSelection, "typing");
    onChange(nextValue);
    setCaretIndex(nextCaret);
  }

  function replaceComposerSelectionWithText(editor: HTMLDivElement, text: string, kind: ComposerEditKind) {
    const currentValue = composerText(editor);
    const selection = composerSelectionOffsets(editor);
    replaceComposerRangeWithText(currentValue, selection, text, kind);
  }

  function replaceComposerRangeWithText(currentValue: string, selection: ComposerSelection, text: string, kind: ComposerEditKind) {
    const boundedSelection = boundComposerSelection(currentValue, selection);
    const nextValue = `${currentValue.slice(0, boundedSelection.start)}${text}${currentValue.slice(boundedSelection.end)}`;
    const nextCaret = boundedSelection.start + text.length;
    const nextSelection = collapsedComposerSelection(nextValue, nextCaret);
    updateCurrentHistorySelection(boundedSelection);
    recordComposerChange(nextValue, nextSelection, kind);
    setPendingSelection(nextValue, nextSelection, true);
    onChange(nextValue);
    setCaretIndex(nextCaret);
    clearDismissedMention();
    requestAnimationFrame(() => {
      const nextEditor = editorRef.current;
      if (!nextEditor) {
        return;
      }
      nextEditor.focus();
      setComposerSelectionOffsets(nextEditor, nextSelection.start, nextSelection.end);
      scrollComposerCaretIntoView(nextEditor);
    });
  }

  function insertDictationTranscript(text: string, result?: { commands?: DictationCommand[] }) {
    const commands = result?.commands || [];
    const commandHandled = applyDictationCommands(commands);
    const transcript = normalizedDictationInsertion(text || insertionTextFromCommands(commands));
    if (!transcript) {
      if (commandHandled) {
        return;
      }
      setDictationError("No speech detected.");
      return;
    }
    const currentSnapshot = historyRef.current.current;
    const currentValue = currentSnapshot.value;
    const selection = boundComposerSelection(currentValue, currentSnapshot);
    replaceComposerRangeWithText(
      currentValue,
      selection,
      dictationInsertionForSelection(currentValue, selection, transcript),
      "dictation",
    );
  }

  function applyDictationCommands(commands: DictationCommand[]): boolean {
    if (!commands.some((command) => command.type === "delete_last_sentence")) {
      return false;
    }
    const currentSnapshot = historyRef.current.current;
    const currentValue = currentSnapshot.value;
    const selection = boundComposerSelection(currentValue, currentSnapshot);
    const before = deleteLastSentence(currentValue.slice(0, selection.start));
    const nextValue = `${before}${currentValue.slice(selection.end)}`;
    const nextSelection = collapsedComposerSelection(nextValue, before.length);
    updateCurrentHistorySelection(selection);
    recordComposerChange(nextValue, nextSelection, "dictation-command");
    setPendingSelection(nextValue, nextSelection, true);
    onChange(nextValue);
    setCaretIndex(before.length);
    clearDismissedMention();
    requestAnimationFrame(() => {
      const nextEditor = editorRef.current;
      if (!nextEditor) {
        return;
      }
      nextEditor.focus();
      setComposerSelectionOffsets(nextEditor, nextSelection.start, nextSelection.end);
      scrollComposerCaretIntoView(nextEditor);
    });
    return true;
  }

  function onComposerKeyDown(event: KeyboardEvent<HTMLDivElement>) {
    if (event.nativeEvent.isComposing) {
      return;
    }
    if (handleComposerHistoryShortcut(event)) {
      return;
    }
    if (handleAppMentionPickerKey(event)) {
      return;
    }
    if (isSkillMentionPanelOpen) {
      if (event.key === "Escape") {
        event.preventDefault();
        setDismissedSkillMention();
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
    if (event.key === "Enter" && (event.shiftKey || event.altKey || isMobileComposerInput())) {
      event.preventDefault();
      replaceComposerSelectionWithText(event.currentTarget, "\n", "newline");
      return;
    }
    if (event.key === "Enter") {
      event.preventDefault();
      onSubmit();
    }
  }

  function onDragOver(event: DragEvent<HTMLDivElement>) {
    if (disabled) {
      return;
    }
    if (hasAppReferenceDragData(event.dataTransfer)) {
      event.preventDefault();
      event.stopPropagation();
      event.dataTransfer.dropEffect = "copy";
      return;
    }
  }

  function onDrop(event: DragEvent<HTMLDivElement>) {
    if (disabled) {
      return;
    }
    if (hasAppReferenceDragData(event.dataTransfer)) {
      event.preventDefault();
      event.stopPropagation();
      const droppedItems = appReferenceMentionItemsFromDataTransfer(event.dataTransfer);
      insertAppMentions(droppedItems);
      return;
    }
  }

  function onPaste(event: ClipboardEvent<HTMLDivElement>) {
    if (disabled) {
      return;
    }
    if (event.clipboardData.files.length) {
      event.preventDefault();
      event.stopPropagation();
      onAddAttachments(Array.from(event.clipboardData.files));
      return;
    }
    const pastedText = normalizePastedComposerText(event.clipboardData.getData("text/plain"));
    if (!pastedText) {
      return;
    }
    event.preventDefault();
    event.stopPropagation();
    replaceComposerSelectionWithText(event.currentTarget, pastedText, "paste");
  }

  function handleComposerHistoryShortcut(event: KeyboardEvent<HTMLDivElement>): boolean {
    const key = event.key.toLowerCase();
    const hasShortcutModifier = event.metaKey || event.ctrlKey;
    const isUndo = hasShortcutModifier && key === "z" && !event.shiftKey && !event.altKey;
    const isRedo = hasShortcutModifier && !event.altKey && ((key === "z" && event.shiftKey) || (key === "y" && !event.shiftKey));
    if (!isUndo && !isRedo) {
      return false;
    }
    event.preventDefault();
    event.stopPropagation();
    applyComposerHistory(isUndo ? "undo" : "redo");
    return true;
  }

  function recordComposerChange(nextValue: string, selection: ComposerSelection, kind: ComposerEditKind) {
    const history = historyRef.current;
    const nextSnapshot = composerHistorySnapshot(nextValue, selection, kind);
    if (sameComposerHistoryState(history.current, nextSnapshot)) {
      historyRef.current = {
        ...history,
        current: {
          ...history.current,
          end: nextSnapshot.end,
          start: nextSnapshot.start,
          timestamp: nextSnapshot.timestamp,
        },
      };
      return;
    }
    const shouldCoalesce = shouldCoalesceComposerTyping(history.current, nextSnapshot);
    const undo = shouldCoalesce ? history.undo : trimComposerHistoryStack([...history.undo, history.current]);
    historyRef.current = {
      current: nextSnapshot,
      redo: [],
      undo,
    };
  }

  function resetComposerHistory(nextValue: string, selection: ComposerSelection) {
    historyRef.current = {
      current: composerHistorySnapshot(nextValue, selection, "external"),
      redo: [],
      undo: [],
    };
  }

  function updateCurrentHistorySelection(selection: ComposerSelection) {
    const history = historyRef.current;
    const boundedSelection = boundComposerSelection(history.current.value, selection);
    historyRef.current = {
      ...history,
      current: {
        ...history.current,
        ...boundedSelection,
      },
    };
  }

  function setPendingSelection(nextValue: string, selection: ComposerSelection, shouldRestore: boolean) {
    const boundedSelection = boundComposerSelection(nextValue, selection);
    pendingSelectionRef.current = boundedSelection;
    pendingCaretIndexRef.current = boundedSelection.end;
    pendingSelectionRestoreRef.current = shouldRestore;
  }

  function applyComposerHistory(direction: "redo" | "undo") {
    const history = historyRef.current;
    const sourceStack = direction === "undo" ? history.undo : history.redo;
    const target = sourceStack.at(-1);
    if (!target) {
      return;
    }
    const nextUndo = direction === "undo" ? history.undo.slice(0, -1) : trimComposerHistoryStack([...history.undo, history.current]);
    const nextRedo = direction === "undo" ? trimComposerHistoryStack([...history.redo, history.current]) : history.redo.slice(0, -1);
    const restoredSnapshot: ComposerHistorySnapshot = {
      ...target,
      kind: "history",
      timestamp: Date.now(),
    };
    historyRef.current = {
      current: restoredSnapshot,
      redo: nextRedo,
      undo: nextUndo,
    };
    applyComposerHistorySnapshot(restoredSnapshot);
  }

  function applyComposerHistorySnapshot(snapshot: ComposerHistorySnapshot) {
    const selection = boundComposerSelection(snapshot.value, snapshot);
    pendingSelectionRef.current = selection;
    pendingCaretIndexRef.current = selection.end;
    pendingSelectionRestoreRef.current = true;
    onChange(snapshot.value);
    setCaretIndex(selection.end);
    clearDismissedMention();
    requestAnimationFrame(() => {
      const editor = editorRef.current;
      if (!editor) {
        return;
      }
      editor.focus();
      setComposerSelectionOffsets(editor, selection.start, selection.end);
      scrollComposerCaretIntoView(editor);
    });
  }

  return {
    dictationError,
    insertDictationTranscript,
    onComposerKeyDown,
    onDragOver,
    onDrop,
    onPaste,
    setDictationError,
    syncCaret,
    updateComposerFromEditor,
  };
}

function composerHistorySnapshot(value: string, selection: ComposerSelection, kind: ComposerEditKind): ComposerHistorySnapshot {
  return {
    ...boundComposerSelection(value, selection),
    kind,
    timestamp: Date.now(),
    value,
  };
}

function collapsedComposerSelection(value: string, caret: number): ComposerSelection {
  const boundedCaret = Math.max(0, Math.min(caret, value.length));
  return { end: boundedCaret, start: boundedCaret };
}

function boundComposerSelection(value: string, selection: ComposerSelection): ComposerSelection {
  const start = Math.max(0, Math.min(selection.start, value.length));
  const end = Math.max(0, Math.min(selection.end, value.length));
  return {
    end: Math.max(start, end),
    start: Math.min(start, end),
  };
}

function sameComposerHistoryState(left: ComposerHistorySnapshot, right: ComposerHistorySnapshot): boolean {
  return left.value === right.value && left.start === right.start && left.end === right.end;
}

function shouldCoalesceComposerTyping(current: ComposerHistorySnapshot, next: ComposerHistorySnapshot): boolean {
  return next.kind === "typing" && current.kind === "typing" && next.timestamp - current.timestamp <= TYPING_COALESCE_MS;
}

function trimComposerHistoryStack(stack: ComposerHistorySnapshot[]): ComposerHistorySnapshot[] {
  return stack.slice(Math.max(0, stack.length - COMPOSER_HISTORY_LIMIT));
}

function insertionTextFromCommands(commands: DictationCommand[]): string {
  const insertCommand = commands.find((command) => command.type === "insert_text" && typeof command.text === "string");
  return insertCommand?.text || "";
}

function normalizedDictationInsertion(text: string): string {
  if (text === "\n" || text === "\n\n") {
    return text;
  }
  return text.trim();
}

function dictationInsertionForSelection(value: string, selection: ComposerSelection, transcript: string): string {
  const before = value.slice(0, selection.start);
  const after = value.slice(selection.end);
  const prefix = before && !/\s$/.test(before) && !transcript.startsWith("\n") && !/^[.,;:!?]/.test(transcript) ? " " : "";
  const suffix = after && !/^\s/.test(after) && !transcript.endsWith("\n") && !/^[.,;:!?]/.test(after) ? " " : "";
  return `${prefix}${transcript}${suffix}`;
}

function deleteLastSentence(text: string): string {
  const stripped = text.replace(/\s+$/g, "");
  if (!stripped) {
    return "";
  }
  let searchIndex = stripped.length - 1;
  if (/[.!?]/.test(stripped[searchIndex] || "")) {
    searchIndex -= 1;
  }
  for (let index = searchIndex; index >= 0; index -= 1) {
    if (/[.!?\n]/.test(stripped[index] || "")) {
      return stripped.slice(0, index + 1).replace(/\s+$/g, "");
    }
  }
  return "";
}
