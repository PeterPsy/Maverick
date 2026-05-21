import {
  type ClipboardEvent,
  type Dispatch,
  type DragEvent,
  type KeyboardEvent,
  type RefObject,
  type SetStateAction,
  useLayoutEffect,
  useState,
} from "react";
import {
  composerCaretOffset,
  composerSelectionOffsets,
  composerText,
  isMobileComposerInput,
  normalizePastedComposerText,
  renderComposerContent,
  setComposerCaret,
} from "../lib/composerDom";
import type { MentionItem, MentionToken } from "../lib/mentions";
import { hasStorageReferenceDragData, storageReferenceMentionItemsFromDataTransfer } from "../lib/storageDragReferences";

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

  useLayoutEffect(() => {
    const editor = editorRef.current;
    if (!editor) {
      return;
    }
    const wasFocused = document.activeElement === editor;
    const nextCaretIndex = pendingCaretIndexRef.current ?? Math.min(caretIndex, value.length);
    pendingCaretIndexRef.current = null;
    renderComposerContent(editor, value, mentionTokens, disabled, onRemoveMention);
    if (wasFocused) {
      setComposerCaret(editor, nextCaretIndex);
    }
  }, [disabled, mentionTokens, value]);

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

  function replaceComposerSelectionWithText(editor: HTMLDivElement, text: string) {
    const currentValue = composerText(editor);
    const selection = composerSelectionOffsets(editor);
    const nextValue = `${currentValue.slice(0, selection.start)}${text}${currentValue.slice(selection.end)}`;
    const nextCaret = selection.start + text.length;
    pendingCaretIndexRef.current = nextCaret;
    onChange(nextValue);
    setCaretIndex(nextCaret);
    clearDismissedMention();
    requestAnimationFrame(() => {
      const nextEditor = editorRef.current;
      if (!nextEditor) {
        return;
      }
      nextEditor.focus();
      setComposerCaret(nextEditor, nextCaret);
    });
  }

  function insertDictationTranscript(text: string) {
    const transcript = text.trim();
    if (!transcript) {
      setDictationError("No speech detected.");
      return;
    }
    const editor = editorRef.current;
    if (!editor) {
      const prefix = value && !/\s$/.test(value) ? " " : "";
      onChange(`${value}${prefix}${transcript}`);
      return;
    }
    const suffix = value && caretIndex < value.length && !/\s$/.test(transcript) ? " " : "";
    replaceComposerSelectionWithText(editor, `${transcript}${suffix}`);
  }

  function onComposerKeyDown(event: KeyboardEvent<HTMLDivElement>) {
    if (event.nativeEvent.isComposing) {
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
      replaceComposerSelectionWithText(event.currentTarget, "\n");
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
    if (hasStorageReferenceDragData(event.dataTransfer)) {
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
    if (hasStorageReferenceDragData(event.dataTransfer)) {
      event.preventDefault();
      event.stopPropagation();
      const droppedItems = storageReferenceMentionItemsFromDataTransfer(event.dataTransfer);
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
    replaceComposerSelectionWithText(event.currentTarget, pastedText);
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
