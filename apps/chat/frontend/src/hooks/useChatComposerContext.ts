import { Dispatch, SetStateAction, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { AppReference, listApps } from "../api/client";
import {
  ActiveAppContext,
  mergeSelectedReferenceMentionItems,
  referenceMentionItem,
} from "../lib/activeAppContext";
import { mentionText, referenceKey } from "../lib/mentions";
import type { MentionItem } from "../lib/mentions";
import { searchComposerReferences } from "../lib/referenceSearch";
import type { ExternalFileDrop, ExternalMentionDrop } from "../lib/externalInputs";

type UseChatComposerContextParams = {
  activeAppContext: ActiveAppContext | null;
  appReferencesAllowed: boolean;
  addAttachments: (files: File[]) => void;
  externalFileDrop: ExternalFileDrop | null;
  externalMentionDrop: ExternalMentionDrop | null;
  navigationScope: string;
  setComposer: Dispatch<SetStateAction<string>>;
  setComposerError: Dispatch<SetStateAction<string | null>>;
  workspaceId: string;
};

export function useChatComposerContext({
  activeAppContext,
  appReferencesAllowed,
  addAttachments,
  externalFileDrop,
  externalMentionDrop,
  navigationScope,
  setComposer,
  setComposerError,
  workspaceId,
}: UseChatComposerContextParams) {
  const [mentionItems, setMentionItems] = useState<MentionItem[]>([]);
  const [selectedReferences, setSelectedReferences] = useState<AppReference[]>([]);
  const consumedExternalFileDrops = useRef<Set<string>>(new Set());
  const consumedExternalMentionDrops = useRef<Set<string>>(new Set());
  const composerMentionItems = useMemo(() => {
    return mergeSelectedReferenceMentionItems(
      appReferencesAllowed ? mentionItems : [],
      appReferencesAllowed ? selectedReferences : [],
    );
  }, [appReferencesAllowed, mentionItems, selectedReferences]);

  useEffect(() => {
    if (!appReferencesAllowed) {
      setSelectedReferences([]);
    }
  }, [appReferencesAllowed]);

  useEffect(() => {
    void loadMentionItems();
  }, []);

  useEffect(() => {
    if (!externalMentionDrop || consumedExternalMentionDrops.current.has(externalMentionDrop.requestId)) {
      return;
    }
    consumedExternalMentionDrops.current.add(externalMentionDrop.requestId);
    appendMentionItemsToComposer(externalMentionDrop.items);
  }, [externalMentionDrop]);

  useEffect(() => {
    if (!externalFileDrop || consumedExternalFileDrops.current.has(externalFileDrop.requestId)) {
      return;
    }
    consumedExternalFileDrops.current.add(externalFileDrop.requestId);
    handleAddAttachments(externalFileDrop.files);
  }, [externalFileDrop]);

  async function loadMentionItems() {
    try {
      const apps = await listApps();
      setMentionItems(apps.map((app) => ({
        id: app.app_id,
        label: app.name,
        description: app.description,
        kind: "app" as const,
      })));
    } catch {
      setMentionItems([]);
    }
  }

  function handleAddAttachments(files: File[]) {
    addAttachments(files);
    setComposerError(null);
  }

  function appendMentionItemsToComposer(items: MentionItem[]) {
    const validItems = items.filter((item) => item.reference);
    if (!validItems.length) {
      return;
    }
    const mentionBlock = validItems.map((item) => mentionText(item)).join(" ");
    setComposer((current) => {
      const prefix = current && !/\s$/.test(current) ? " " : "";
      return `${current}${prefix}${mentionBlock} `;
    });
    validItems.forEach((item) => {
      if (item.reference) {
        handleReferenceAdd(item.reference);
      }
    });
    setComposerError(null);
  }

  const handleSearchReferences = useCallback(
    async (query: string, signal: AbortSignal): Promise<MentionItem[]> => {
      if (!appReferencesAllowed) {
        return [];
      }
      const references = await searchComposerReferences(query, signal, activeAppContext?.app_id || "", workspaceId);
      return references.map(referenceMentionItem);
    },
    [activeAppContext?.app_id, appReferencesAllowed, workspaceId],
  );

  function handleReferenceAdd(reference: AppReference) {
    if (!appReferencesAllowed) {
      setComposerError("The selected runtime profile does not allow app references.");
      return;
    }
    setSelectedReferences((current) => {
      const key = referenceKey(reference);
      return current.some((item) => referenceKey(item) === key) ? current : [...current, reference];
    });
  }

  function handleReferenceRemove(reference: AppReference) {
    const key = referenceKey(reference);
    setSelectedReferences((current) => current.filter((item) => referenceKey(item) !== key));
  }

  function handleCapturePageArea() {
    window.parent?.postMessage(
      {
        type: "maverick.shell.capture-area.start",
        owner_app_id: "chat",
        widget_id: "chat-floating",
        navigation_scope: navigationScope,
      },
      "*",
    );
  }

  return {
    composerMentionItems,
    handleAddAttachments,
    handleCapturePageArea,
    handleReferenceAdd,
    handleReferenceRemove,
    handleSearchReferences,
    mentionItems,
    selectedReferences,
    setSelectedReferences,
  };
}
