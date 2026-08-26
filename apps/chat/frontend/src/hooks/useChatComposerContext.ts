import { Dispatch, SetStateAction, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { AppReference, getSourceAppChatCapabilities, listApps, listSkills } from "../api/client";
import type { ProviderItem } from "../api/client";
import {
  ActiveAppContext,
  mergeSelectedReferenceMentionItems,
  referenceMentionItem,
} from "../lib/activeAppContext";
import { mentionText, referenceKey } from "../lib/mentions";
import type { MentionItem } from "../lib/mentions";
import { searchComposerReferences } from "../lib/referenceSearch";
import type { ExternalFileDrop, ExternalMentionDrop } from "../lib/externalInputs";
import { skillIdsVisibleInComposer } from "../lib/skillMentionPolicy";

type UseChatComposerContextParams = {
  activeAppContext: ActiveAppContext | null;
  appReferencesAllowed: boolean;
  addAttachments: (files: File[]) => void;
  externalFileDrop: ExternalFileDrop | null;
  externalMentionDrop: ExternalMentionDrop | null;
  navigationScope: string;
  skillMentionContext: {
    activationMode?: string;
    allowedSkillIds?: string[];
    provider: ProviderItem | null;
    sourceAppId?: string;
  };
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
  skillMentionContext,
  setComposer,
  setComposerError,
  workspaceId,
}: UseChatComposerContextParams) {
  const [mentionItems, setMentionItems] = useState<MentionItem[]>([]);
  const [selectedReferences, setSelectedReferences] = useState<AppReference[]>([]);
  const [sourceAppSupportsSkillInvocations, setSourceAppSupportsSkillInvocations] = useState(false);
  const consumedExternalFileDrops = useRef<Set<string>>(new Set());
  const consumedExternalMentionDrops = useRef<Set<string>>(new Set());
  const composerMentionItems = useMemo(() => {
    const visibleSkillIds = new Set(skillIdsVisibleInComposer({
      activationMode: skillMentionContext.activationMode,
      allowedSkillIds: skillMentionContext.allowedSkillIds,
      availableSkillIds: mentionItems.filter((item) => item.kind === "skill").map((item) => item.id),
      provider: skillMentionContext.provider,
      sourceAppId: skillMentionContext.sourceAppId,
      sourceAppSupportsSkillInvocations,
    }));
    const governedItems = mentionItems.filter((item) => (
      (item.kind !== "skill" || visibleSkillIds.has(item.id))
      && (appReferencesAllowed || item.kind === "skill")
    ));
    return mergeSelectedReferenceMentionItems(
      governedItems,
      appReferencesAllowed ? selectedReferences : [],
    );
  }, [appReferencesAllowed, mentionItems, selectedReferences, skillMentionContext, sourceAppSupportsSkillInvocations]);

  useEffect(() => {
    if (!appReferencesAllowed) {
      setSelectedReferences([]);
    }
  }, [appReferencesAllowed]);

  useEffect(() => {
    void loadMentionItems();
  }, []);

  useEffect(() => {
    const sourceAppId = skillMentionContext.sourceAppId || "";
    setSourceAppSupportsSkillInvocations(false);
    if (!sourceAppId) {
      return;
    }
    const abortController = new AbortController();
    void getSourceAppChatCapabilities(sourceAppId, { signal: abortController.signal })
      .then((capabilities) => {
        setSourceAppSupportsSkillInvocations(capabilities.supports_skill_invocations === true);
      })
      .catch(() => {
        if (!abortController.signal.aborted) {
          setSourceAppSupportsSkillInvocations(false);
        }
      });
    return () => abortController.abort();
  }, [skillMentionContext.sourceAppId]);

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
      setComposerError("The selected runtime profile is not certified for app references.");
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
