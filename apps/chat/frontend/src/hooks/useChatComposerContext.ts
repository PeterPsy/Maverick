import { Dispatch, SetStateAction, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { AppReference, listApps, listSkills } from "../api/client";
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
  const composerMentionItems = useMemo(
    () => mergeSelectedReferenceMentionItems(mentionItems, selectedReferences),
    [mentionItems, selectedReferences],
  );

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
    const [appsResult, skillsResult] = await Promise.allSettled([listApps(), listSkills()]);
    const appMentions =
      appsResult.status === "fulfilled"
        ? appsResult.value.map((app) => ({
            id: app.app_id,
            label: app.name,
            description: app.description,
            kind: "app" as const,
          }))
        : [];
    const skillMentions =
      skillsResult.status === "fulfilled"
        ? skillsResult.value.map((skill) => ({
            id: skill.id,
            label: skill.name,
            description: skill.description,
            kind: "skill" as const,
          }))
        : [];
    setMentionItems([...appMentions, ...skillMentions]);
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
      const references = await searchComposerReferences(query, signal, activeAppContext?.app_id || "", workspaceId);
      return references.map(referenceMentionItem);
    },
    [activeAppContext?.app_id, workspaceId],
  );

  function handleReferenceAdd(reference: AppReference) {
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
      window.location.origin,
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
    setSelectedReferences,
  };
}
