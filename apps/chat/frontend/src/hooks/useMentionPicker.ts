import { type Dispatch, type KeyboardEvent, type RefObject, type SetStateAction, useEffect, useMemo, useRef, useState } from "react";
import type { AppReference } from "../api/client";
import { setComposerCaret } from "../lib/composerDom";
import {
  activeMentionAt,
  applyMention,
  filterMentionItems,
  findMentionTokens,
  mentionText,
  removeMentionToken,
} from "../lib/mentions";
import type { ActiveMention, MentionItem, MentionToken } from "../lib/mentions";
import { useAppPickerDismiss } from "./useAppPickerDismiss";
import { mergeMentionItems } from "./mentionPickerUtils";
import { useAppReferenceSearch } from "./useAppReferenceSearch";

const APP_PICKER_REFERENCE_LIMIT = 16;
function focusEditorAtCaret(editorRef: RefObject<HTMLDivElement | null>, caret: number) {
  requestAnimationFrame(() => {
    const editor = editorRef.current;
    if (!editor) {
      return;
    }
    editor.focus();
    setComposerCaret(editor, caret);
  });
}
type UseMentionPickerParams = {
  caretIndex: number;
  editorRef: RefObject<HTMLDivElement | null>;
  mentionItems: MentionItem[];
  onChange: (value: string) => void;
  onReferenceAdd?: (reference: AppReference) => void;
  onReferenceRemove?: (reference: AppReference) => void;
  onSearchReferences?: (query: string, signal: AbortSignal) => Promise<MentionItem[]>;
  pendingCaretIndexRef: RefObject<number | null>;
  setCaretIndex: Dispatch<SetStateAction<number>>;
  value: string;
};
export function useMentionPicker({
  caretIndex,
  editorRef,
  mentionItems,
  onChange,
  onReferenceAdd,
  onReferenceRemove,
  onSearchReferences,
  pendingCaretIndexRef,
  setCaretIndex,
  value,
}: UseMentionPickerParams) {
  const [dismissedMentionStart, setDismissedMentionStart] = useState<number | null>(null);
  const [selectedMentionIndex, setSelectedMentionIndex] = useState(0);
  const [showAppPicker, setShowAppPicker] = useState(false);
  const [selectedAppIndex, setSelectedAppIndex] = useState(0);
  const [appPickerQuery, setAppPickerQuery] = useState("");
  const [appPickerReferenceItems, setAppPickerReferenceItems] = useState<MentionItem[]>([]);
  const [appPickerSearchError, setAppPickerSearchError] = useState<string | null>(null);
  const [appPickerSearchPending, setAppPickerSearchPending] = useState(false);
  const appPickerButtonRef = useRef<HTMLButtonElement | null>(null);
  const appPickerPanelRef = useRef<HTMLDivElement | null>(null);
  const appPickerSearchRef = useRef<HTMLInputElement | null>(null);
  const activeMentionCandidate = useMemo(() => activeMentionAt(value, caretIndex), [caretIndex, value]);
  const isMentionCandidateDismissed = activeMentionCandidate?.start === dismissedMentionStart;
  const searchableMentionItems = useMemo(
    () => mergeMentionItems(mentionItems, appPickerReferenceItems),
    [appPickerReferenceItems, mentionItems],
  );
  const mentionTokens = useMemo(() => findMentionTokens(value, searchableMentionItems), [searchableMentionItems, value]);
  const activeMentionComplete = activeMentionCandidate
    ? mentionTokens.some((token) => token.start === activeMentionCandidate.start && caretIndex >= token.end)
    : false;
  const activeMention = isMentionCandidateDismissed || activeMentionComplete ? null : activeMentionCandidate;
  const activeAppMention = activeMention?.kind === "app" ? activeMention : null;
  const activeSkillMention = activeMention?.kind === "skill" ? activeMention : null;
  const isAppMentionPickerOpen = showAppPicker || Boolean(activeAppMention);
  const appMentionPickerQuery = activeAppMention ? activeAppMention.query : appPickerQuery;
  useAppReferenceSearch({
    isOpen: isAppMentionPickerOpen,
    onSearchReferences,
    query: appMentionPickerQuery,
    setError: setAppPickerSearchError,
    setItems: setAppPickerReferenceItems,
    setPending: setAppPickerSearchPending,
  });
  const appPickerItems = useMemo(() => {
    const matchingApps = filterMentionItems(
      searchableMentionItems.filter((item) => item.kind === "app"),
      appMentionPickerQuery,
    );
    const matchingReferences = filterMentionItems(appPickerReferenceItems, appMentionPickerQuery, APP_PICKER_REFERENCE_LIMIT);
    return mergeMentionItems(matchingApps, matchingReferences);
  }, [appMentionPickerQuery, appPickerReferenceItems, searchableMentionItems]);
  const filteredMentionItems = useMemo(() => {
    if (!activeSkillMention) {
      return [];
    }
    return filterMentionItems(
      searchableMentionItems.filter((item) => item.kind === activeSkillMention.kind),
      activeSkillMention.query,
    );
  }, [activeSkillMention, searchableMentionItems]);
  const isSkillMentionPanelOpen = Boolean(activeSkillMention);

  useEffect(() => {
    setSelectedMentionIndex(0);
  }, [activeSkillMention?.kind, activeSkillMention?.query]);
  useEffect(() => {
    setSelectedAppIndex(0);
  }, [appPickerItems]);
  useEffect(() => {
    if (showAppPicker) {
      appPickerSearchRef.current?.focus();
    }
  }, [showAppPicker]);

  useAppPickerDismiss({
    activeAppMention,
    appPickerButtonRef,
    appPickerPanelRef,
    dismissedMentionStart,
    isOpen: isAppMentionPickerOpen,
    setDismissedMentionStart,
    setShowAppPicker,
    showAppPicker,
    value,
  });

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
    focusEditorAtCaret(editorRef, next.cursor);
  }

  function updateActiveAppMentionQuery(query: string) {
    if (!activeAppMention) {
      setAppPickerQuery(query);
      return;
    }
    const nextValue = `${value.slice(0, activeAppMention.start + 1)}${query}${value.slice(activeAppMention.end)}`;
    const nextCaret = activeAppMention.start + 1 + query.length;
    pendingCaretIndexRef.current = nextCaret;
    onChange(nextValue);
    setCaretIndex(nextCaret);
    setDismissedMentionStart(null);
  }

  function selectAppMentionPickerItem(item: MentionItem) {
    if (activeAppMention && !showAppPicker) {
      insertMention(item);
      return;
    }
    insertAppMention(item);
  }

  function removeMention(token: MentionToken) {
    const next = removeMentionToken(value, token);
    pendingCaretIndexRef.current = next.cursor;
    onChange(next.value);
    if (token.item.reference) {
      onReferenceRemove?.(token.item.reference);
    }
    setCaretIndex(next.cursor);
    focusEditorAtCaret(editorRef, next.cursor);
  }

  function insertAppMention(item: MentionItem) {
    insertAppMentions([item]);
  }

  function insertAppMentions(items: MentionItem[]) {
    if (!items.length) {
      return;
    }
    const boundedCaret = Math.max(0, Math.min(caretIndex, value.length));
    const before = value.slice(0, boundedCaret);
    const after = value.slice(boundedCaret);
    const prefix = before && !/\s$/.test(before) ? " " : "";
    const suffix = after && /^\s/.test(after) ? "" : " ";
    const insertion = `${prefix}${items.map((item) => mentionText(item)).join(" ")}${suffix}`;
    const nextValue = `${before}${insertion}${after}`;
    const nextCaret = before.length + insertion.length;
    pendingCaretIndexRef.current = nextCaret;
    onChange(nextValue);
    for (const item of items) {
      if (item.reference) {
        onReferenceAdd?.(item.reference);
      }
    }
    setCaretIndex(nextCaret);
    setDismissedMentionStart(null);
    setShowAppPicker(false);
    setAppPickerQuery("");
    setAppPickerSearchError(null);
    focusEditorAtCaret(editorRef, nextCaret);
  }

  function closeAppMentionPicker(focusEditor = false) {
    if (showAppPicker) {
      setShowAppPicker(false);
    } else if (activeAppMention) {
      setDismissedMentionStart(activeAppMention.start);
    }
    setAppPickerSearchError(null);
    if (focusEditor) {
      focusEditorAtCaret(editorRef, caretIndex);
    }
  }

  function handleAppMentionPickerKey(event: KeyboardEvent<HTMLElement>, focusEditorOnClose = false): boolean {
    if (!isAppMentionPickerOpen) {
      return false;
    }
    if (event.key === "Escape") {
      event.preventDefault();
      closeAppMentionPicker(focusEditorOnClose);
      return true;
    }
    if (!appPickerItems.length) {
      if (event.key === "Enter") {
        event.preventDefault();
        return true;
      }
      return false;
    }
    if (event.key === "ArrowDown") {
      event.preventDefault();
      setSelectedAppIndex((current) => (current + 1) % appPickerItems.length);
      return true;
    }
    if (event.key === "ArrowUp") {
      event.preventDefault();
      setSelectedAppIndex((current) => (current - 1 + appPickerItems.length) % appPickerItems.length);
      return true;
    }
    if (event.key === "Tab" || event.key === "Enter") {
      event.preventDefault();
      selectAppMentionPickerItem(appPickerItems[selectedAppIndex] || appPickerItems[0]);
      return true;
    }
    return false;
  }

  function dismissSkillMention(mention: ActiveMention | null) {
    setDismissedMentionStart(mention?.start ?? null);
  }

  function clearDismissedMention() {
    setDismissedMentionStart(null);
  }

  function openAppPicker() {
    if (isAppMentionPickerOpen) {
      closeAppMentionPicker();
      return;
    }
    setAppPickerQuery("");
    setAppPickerSearchError(null);
    setShowAppPicker(true);
  }

  return {
    activeSkillMention,
    appMentionPickerQuery,
    appPickerButtonRef,
    appPickerItems,
    appPickerPanelRef,
    appPickerSearchError,
    appPickerSearchPending,
    appPickerSearchRef,
    clearDismissedMention,
    closeAppMentionPicker,
    dismissSkillMention,
    filteredMentionItems,
    handleAppMentionPickerKey,
    insertAppMentions,
    insertMention,
    isAppMentionPickerOpen,
    isSkillMentionPanelOpen,
    mentionTokens,
    openAppPicker,
    removeMention,
    selectAppMentionPickerItem,
    selectedAppIndex,
    selectedMentionIndex,
    setSelectedMentionIndex,
    updateActiveAppMentionQuery,
  };
}
