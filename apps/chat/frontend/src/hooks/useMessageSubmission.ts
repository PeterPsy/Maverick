import { Dispatch, SetStateAction, useCallback, useEffect, useRef, useState } from "react";
import {
  AppReference,
  ChatThread,
  InterAgentRunDetail,
  MultiAgentComposerMode,
  RuntimeEvent,
  RuntimeSession,
  RuntimeTurn,
  type CreateInterAgentRunPayload,
  type InterAgentParticipantSpecPayload,
  createInterAgentRun,
  createRuntimeSession,
  createRuntimeSessionWithTurn,
  executeInterAgentRun,
  interruptRuntimeTurn,
  sendRuntimeTurn,
} from "../api/client";
import type { ComposerAttachment } from "../lib/attachments";
import { hasInvalidAttachments } from "../lib/attachments";
import { ActiveAppContext, mergeAppReferences } from "../lib/activeAppContext";
import { appReferencesFromText } from "../lib/mentions";
import type { MentionItem } from "../lib/mentions";
import { PendingMessage, QueuedMessage, attachmentToMessageAttachment, uploadComposerAttachment } from "../lib/messageState";
import { mergeRuntimeEvents } from "../lib/runtimeEvents";
import { loadDefaultSystemPrompt } from "../lib/activeAppContext";
import { migratePersistedQueuedMessages } from "../lib/queuedMessages";
import { openChatThreadRouteInShell } from "../lib/shellNavigation";
import { upsertOrderedThread } from "../lib/threadNavigation";

export type DraftChat = {
  draftId: string;
  projectId: string | null;
  systemPrompt: string;
};

export type AgentRuntimeConfig = {
  agent_id: string;
  agent_role_id: string;
  agent_type_id: string;
  runtime_mode?: "agentic" | "plain_hosted_chat";
  routing_profile?: string;
  hosted_provider_id?: string;
  hosted_model_id?: string;
  skill_catalog_app_id: string;
  skill_ids: string[];
  source_app_id: string;
  system_prompt: string;
  title: string;
};

type InterAgentWorkerPlan = {
  participantId: string;
  label: string;
  task: string;
};

type UseMessageSubmissionParams = {
  activeAppContext: ActiveAppContext | null;
  activeThread: ChatThread | null;
  attachments: ComposerAttachment[];
  clearAttachments: () => void;
  composer: string;
  composerMentionItems: MentionItem[];
  draftChat: DraftChat | null;
  isBootstrapping: boolean;
  isHistoryLoading: boolean;
  isRuntimeBusy: boolean;
  multiAgentMode: MultiAgentComposerMode;
  navigationScope: string;
  notifyActiveThreadChanged: (activeThreadId: string) => void;
  onInterAgentRunChanged?: (detail: InterAgentRunDetail) => void;
  selectedAgentRuntimeConfig: (activeApp: ActiveAppContext | null) => Promise<AgentRuntimeConfig | null>;
  setActiveSession: Dispatch<SetStateAction<RuntimeSession | null>>;
  setActiveThread: Dispatch<SetStateAction<ChatThread | null>>;
  setActiveTurn: Dispatch<SetStateAction<RuntimeTurn | null>>;
  setComposer: Dispatch<SetStateAction<string>>;
  setComposerError: Dispatch<SetStateAction<string | null>>;
  setDraftChat: Dispatch<SetStateAction<DraftChat | null>>;
  setError: Dispatch<SetStateAction<string | null>>;
  setEvents: Dispatch<SetStateAction<RuntimeEvent[]>>;
  setSelectedReferences: Dispatch<SetStateAction<AppReference[]>>;
  setThreads: Dispatch<SetStateAction<ChatThread[]>>;
  threads: ChatThread[];
};

type ConversationItems<T> = Record<string, T[]>;

type InFlightSubmission = {
  abortController: AbortController;
  clientMessageId: string;
  turnId?: string;
};

type SubmissionTarget = {
  activeAppContext: ActiveAppContext | null;
  conversationKey: string;
  draftChat: DraftChat | null;
  thread: ChatThread | null;
  threadIds: Set<string>;
};

export function conversationKeyFor(activeThread: ChatThread | null, draftChat: DraftChat | null): string {
  if (activeThread?.thread_id) {
    return `thread:${activeThread.thread_id}`;
  }
  if (draftChat?.draftId) {
    return `draft:${draftChat.draftId}`;
  }
  return "";
}

function threadConversationKey(threadId: string): string {
  return `thread:${threadId}`;
}

function itemsForConversation<T>(itemsByConversationKey: ConversationItems<T>, conversationKey: string): T[] {
  return conversationKey ? itemsByConversationKey[conversationKey] || [] : [];
}

function setItemsForConversation<T>(
  setter: Dispatch<SetStateAction<ConversationItems<T>>>,
  conversationKey: string,
  action: SetStateAction<T[]>,
) {
  if (!conversationKey) {
    return;
  }
  setter((current) => {
    const currentItems = current[conversationKey] || [];
    const nextItems = typeof action === "function" ? (action as (previous: T[]) => T[])(currentItems) : action;
    if (!nextItems.length) {
      const { [conversationKey]: _removed, ...remaining } = current;
      return remaining;
    }
    return { ...current, [conversationKey]: nextItems };
  });
}

function isAbortError(error: unknown): boolean {
  return typeof DOMException !== "undefined" && error instanceof DOMException
    ? error.name === "AbortError"
    : error instanceof Error && error.name === "AbortError";
}

function throwIfAborted(signal: AbortSignal) {
  if (!signal.aborted) {
    return;
  }
  if (typeof DOMException !== "undefined") {
    throw new DOMException("Message submission was stopped.", "AbortError");
  }
  const error = new Error("Message submission was stopped.");
  error.name = "AbortError";
  throw error;
}

export function useMessageSubmission({
  activeAppContext,
  activeThread,
  attachments,
  clearAttachments,
  composer,
  composerMentionItems,
  draftChat,
  isBootstrapping,
  isHistoryLoading,
  isRuntimeBusy,
  multiAgentMode,
  navigationScope,
  notifyActiveThreadChanged,
  onInterAgentRunChanged,
  selectedAgentRuntimeConfig,
  setActiveSession,
  setActiveThread,
  setActiveTurn,
  setComposer,
  setComposerError,
  setDraftChat,
  setError,
  setEvents,
  setSelectedReferences,
  setThreads,
  threads,
}: UseMessageSubmissionParams) {
  const activeConversationKey = conversationKeyFor(activeThread, draftChat);
  const activeConversationKeyRef = useRef(activeConversationKey);
  const activeAppContextRef = useRef(activeAppContext);
  const activeThreadRef = useRef(activeThread);
  const draftChatRef = useRef(draftChat);
  const threadsRef = useRef(threads);
  const conversationKeyAliasesRef = useRef<Record<string, string>>({});
  const inFlightSubmissionsRef = useRef<Record<string, InFlightSubmission>>({});
  const [pendingUserMessagesByConversationKey, setPendingUserMessagesByConversationKey] = useState<ConversationItems<PendingMessage>>({});
  const [failedUserMessagesByConversationKey, setFailedUserMessagesByConversationKey] = useState<ConversationItems<PendingMessage>>({});
  const [queuedMessagesByConversationKey, setQueuedMessagesByConversationKey] = useState<ConversationItems<QueuedMessage>>({});
  const [sendingByConversationKey, setSendingByConversationKey] = useState<Record<string, true>>({});
  const [submittedTurnByConversationKey, setSubmittedTurnByConversationKey] = useState<Record<string, string>>({});
  const pendingUserMessages = itemsForConversation(pendingUserMessagesByConversationKey, activeConversationKey);
  const failedUserMessages = itemsForConversation(failedUserMessagesByConversationKey, activeConversationKey);
  const queuedMessages = itemsForConversation(queuedMessagesByConversationKey, activeConversationKey);
  const isSending = Boolean(activeConversationKey && sendingByConversationKey[activeConversationKey]);
  const activeSubmissionTurnId = activeConversationKey ? submittedTurnByConversationKey[activeConversationKey] || "" : "";

  useEffect(() => {
    activeConversationKeyRef.current = activeConversationKey;
    activeAppContextRef.current = activeAppContext;
    activeThreadRef.current = activeThread;
    draftChatRef.current = draftChat;
    threadsRef.current = threads;
  }, [activeAppContext, activeConversationKey, activeThread, draftChat, threads]);

  const setPendingUserMessages = useCallback<Dispatch<SetStateAction<PendingMessage[]>>>((action) => {
    setItemsForConversation(setPendingUserMessagesByConversationKey, activeConversationKeyRef.current, action);
  }, []);

  const setFailedUserMessages = useCallback<Dispatch<SetStateAction<PendingMessage[]>>>((action) => {
    setItemsForConversation(setFailedUserMessagesByConversationKey, activeConversationKeyRef.current, action);
  }, []);

  const setQueuedMessages = useCallback<Dispatch<SetStateAction<QueuedMessage[]>>>((action) => {
    setItemsForConversation(setQueuedMessagesByConversationKey, activeConversationKeyRef.current, action);
  }, []);

  const setPendingUserMessagesForConversation = useCallback((conversationKey: string, action: SetStateAction<PendingMessage[]>) => {
    setItemsForConversation(setPendingUserMessagesByConversationKey, conversationKey, action);
  }, []);

  const setFailedUserMessagesForConversation = useCallback((conversationKey: string, action: SetStateAction<PendingMessage[]>) => {
    setItemsForConversation(setFailedUserMessagesByConversationKey, conversationKey, action);
  }, []);

  const setQueuedMessagesForConversation = useCallback((conversationKey: string, action: SetStateAction<QueuedMessage[]>) => {
    setItemsForConversation(setQueuedMessagesByConversationKey, conversationKey, action);
  }, []);

  function setConversationSending(conversationKey: string, isConversationSending: boolean) {
    setSendingByConversationKey((current) => {
      if (!conversationKey) {
        return current;
      }
      if (isConversationSending) {
        return { ...current, [conversationKey]: true };
      }
      const { [conversationKey]: _removed, ...remaining } = current;
      return remaining;
    });
  }

  function setSubmittedTurnForConversation(conversationKey: string, turnId: string | null) {
    setSubmittedTurnByConversationKey((current) => {
      if (!conversationKey) {
        return current;
      }
      if (turnId) {
        return { ...current, [conversationKey]: turnId };
      }
      const { [conversationKey]: _removed, ...remaining } = current;
      return remaining;
    });
  }

  function removePendingMessage(conversationKey: string, clientMessageId: string) {
    setItemsForConversation(setPendingUserMessagesByConversationKey, conversationKey, (current) =>
      current.filter((item) => item.clientMessageId !== clientMessageId),
    );
  }

  function replacePendingMessage(conversationKey: string, message: QueuedMessage) {
    setItemsForConversation(setPendingUserMessagesByConversationKey, conversationKey, (current) =>
      current.map((item) =>
        item.clientMessageId === message.clientMessageId
          ? {
              ...item,
              attachments: message.attachments,
              appReferences: message.appReferences,
              content: message.content,
            }
          : item,
      ),
    );
  }

  function addFailedMessage(conversationKey: string, message: QueuedMessage) {
    setItemsForConversation(setFailedUserMessagesByConversationKey, conversationKey, (current) => [
      ...current,
      {
        clientMessageId: message.clientMessageId,
        content: message.content,
        createdAt: new Date().toISOString(),
        attachments: message.attachments,
        appReferences: message.appReferences,
      },
    ]);
  }

  function migrateConversationState(fromConversationKey: string, toConversationKey: string) {
    if (!fromConversationKey || !toConversationKey || fromConversationKey === toConversationKey) {
      return;
    }
    conversationKeyAliasesRef.current[fromConversationKey] = toConversationKey;
    migratePersistedQueuedMessages(navigationScope, fromConversationKey, toConversationKey);
    setPendingUserMessagesByConversationKey((current) => {
      const items = current[fromConversationKey] || [];
      if (!items.length) {
        return current;
      }
      const { [fromConversationKey]: _removed, ...remaining } = current;
      return { ...remaining, [toConversationKey]: [...(remaining[toConversationKey] || []), ...items] };
    });
    setFailedUserMessagesByConversationKey((current) => {
      const items = current[fromConversationKey] || [];
      if (!items.length) {
        return current;
      }
      const { [fromConversationKey]: _removed, ...remaining } = current;
      return { ...remaining, [toConversationKey]: [...(remaining[toConversationKey] || []), ...items] };
    });
    setQueuedMessagesByConversationKey((current) => {
      const items = current[fromConversationKey] || [];
      if (!items.length) {
        return current;
      }
      const { [fromConversationKey]: _removed, ...remaining } = current;
      return { ...remaining, [toConversationKey]: [...(remaining[toConversationKey] || []), ...items] };
    });
    setSubmittedTurnByConversationKey((current) => {
      const turnId = current[fromConversationKey];
      if (!turnId) {
        return current;
      }
      const { [fromConversationKey]: _removed, ...remaining } = current;
      return { ...remaining, [toConversationKey]: turnId };
    });
    const inFlight = inFlightSubmissionsRef.current[fromConversationKey];
    if (inFlight) {
      delete inFlightSubmissionsRef.current[fromConversationKey];
      inFlightSubmissionsRef.current[toConversationKey] = inFlight;
    }
  }

  function isConversationStillActive(conversationKey: string): boolean {
    return Boolean(conversationKey && activeConversationKeyRef.current === conversationKey);
  }

  function resolveConversationKeyAlias(conversationKey: string): string {
    let resolvedConversationKey = conversationKey;
    const seenConversationKeys = new Set<string>();
    while (conversationKeyAliasesRef.current[resolvedConversationKey] && !seenConversationKeys.has(resolvedConversationKey)) {
      seenConversationKeys.add(resolvedConversationKey);
      resolvedConversationKey = conversationKeyAliasesRef.current[resolvedConversationKey];
    }
    return resolvedConversationKey;
  }

  function currentSubmissionTarget(conversationKey = activeConversationKeyRef.current): SubmissionTarget | null {
    const targetThread = activeThreadRef.current;
    const targetDraftChat = draftChatRef.current;
    const targetConversationKey = conversationKeyFor(targetThread, targetDraftChat);
    if (!conversationKey || targetConversationKey !== conversationKey) {
      return null;
    }
    return {
      activeAppContext: activeAppContextRef.current,
      conversationKey,
      draftChat: targetDraftChat,
      thread: targetThread,
      threadIds: new Set(threadsRef.current.map((item) => item.thread_id)),
    };
  }

  function hasTargetThread(target: SubmissionTarget, thread: ChatThread | null): thread is ChatThread {
    return Boolean(thread && (target.threadIds.has(thread.thread_id) || target.thread?.thread_id === thread.thread_id));
  }

  function startSubmission(target: SubmissionTarget, message: QueuedMessage): AbortController {
    const abortController = new AbortController();
    inFlightSubmissionsRef.current[target.conversationKey] = {
      abortController,
      clientMessageId: message.clientMessageId,
    };
    setItemsForConversation(setPendingUserMessagesByConversationKey, target.conversationKey, (current) => [
      ...current,
      {
        clientMessageId: message.clientMessageId,
        content: message.content,
        createdAt: new Date().toISOString(),
        attachments: message.attachments,
        appReferences: message.appReferences,
      },
    ]);
    setItemsForConversation(setFailedUserMessagesByConversationKey, target.conversationKey, (current) =>
      current.filter((item) => item.clientMessageId !== message.clientMessageId),
    );
    setConversationSending(target.conversationKey, true);
    if (isConversationStillActive(target.conversationKey)) {
      setError(null);
    }
    return abortController;
  }

  function clearSubmission(target: SubmissionTarget, clientMessageId: string) {
    removePendingMessage(target.conversationKey, clientMessageId);
    setSubmittedTurnForConversation(target.conversationKey, null);
    delete inFlightSubmissionsRef.current[target.conversationKey];
    setConversationSending(target.conversationKey, false);
  }

  async function uploadAttachmentWithAbort(attachment: ComposerAttachment, signal: AbortSignal) {
    throwIfAborted(signal);
    return new Promise<Awaited<ReturnType<typeof uploadComposerAttachment>>>((resolve, reject) => {
      let settled = false;
      const cleanup = () => {
        signal.removeEventListener("abort", abort);
      };
      const abort = () => {
        if (settled) {
          return;
        }
        settled = true;
        cleanup();
        reject(abortError());
      };
      signal.addEventListener("abort", abort, { once: true });
      void uploadComposerAttachment(attachment).then(
        (uploadedAttachment) => {
          if (settled) {
            return;
          }
          settled = true;
          cleanup();
          if (signal.aborted) {
            reject(abortError());
            return;
          }
          resolve(uploadedAttachment);
        },
        (uploadError) => {
          if (settled) {
            return;
          }
          settled = true;
          cleanup();
          reject(uploadError);
        },
      );
    });
  }

  function abortError(): Error | DOMException {
    if (typeof DOMException !== "undefined") {
      return new DOMException("Message submission was stopped.", "AbortError");
    }
    const error = new Error("Message submission was stopped.");
    error.name = "AbortError";
    return error;
  }

  async function uploadAttachmentsWithAbort(attachmentsToUpload: ComposerAttachment[], signal: AbortSignal) {
    if (!attachmentsToUpload.length) {
      throwIfAborted(signal);
      return [];
    }
    const uploadedAttachments = await Promise.all(attachmentsToUpload.map((attachment) => uploadAttachmentWithAbort(attachment, signal)));
    throwIfAborted(signal);
    return uploadedAttachments;
  }

  async function stopActiveSubmission(): Promise<boolean> {
    const conversationKey = activeConversationKeyRef.current;
    const inFlightSubmission = inFlightSubmissionsRef.current[conversationKey];
    const turnId = (conversationKey && submittedTurnByConversationKey[conversationKey]) || inFlightSubmission?.turnId || "";
    if (!conversationKey || (!inFlightSubmission && !turnId)) {
      return false;
    }
    if (!turnId) {
      inFlightSubmission?.abortController.abort();
      if (inFlightSubmission?.clientMessageId) {
        removePendingMessage(conversationKey, inFlightSubmission.clientMessageId);
      }
      delete inFlightSubmissionsRef.current[conversationKey];
      setConversationSending(conversationKey, false);
      setSubmittedTurnForConversation(conversationKey, null);
      return true;
    }
    try {
      const response = await interruptRuntimeTurn(turnId);
      if (isConversationStillActive(conversationKey)) {
        setActiveTurn(response.turn);
        if (response.event) {
          setEvents((current) => mergeRuntimeEvents(current, [response.event as RuntimeEvent]));
        }
        setError(null);
      }
      if (inFlightSubmission?.clientMessageId) {
        removePendingMessage(conversationKey, inFlightSubmission.clientMessageId);
      }
      delete inFlightSubmissionsRef.current[conversationKey];
      setConversationSending(conversationKey, false);
      setSubmittedTurnForConversation(conversationKey, null);
      return true;
    } catch (stopError) {
      if (isConversationStillActive(conversationKey)) {
        setError(stopError instanceof Error ? stopError.message : "Unable to stop runtime turn.");
      }
      return true;
    }
  }

  async function submitMessage(message: QueuedMessage, target: SubmissionTarget, abortController: AbortController) {
    const conversationKey = target.conversationKey;
    const targetThread = target.thread;
    const targetDraftChat = target.draftChat;
    try {
      throwIfAborted(abortController.signal);
      if (message.multiAgentMode && message.multiAgentMode !== "off") {
        await submitInterAgentMessage(message, target, abortController.signal);
        return;
      }
      let thread = targetThread;
      let response: Awaited<ReturnType<typeof sendRuntimeTurn>>;
      if (!thread) {
        const agentRuntimeConfig = await selectedAgentRuntimeConfig(target.activeAppContext);
        throwIfAborted(abortController.signal);
        const systemPrompt =
          agentRuntimeConfig?.system_prompt || targetDraftChat?.systemPrompt || (await loadDefaultSystemPrompt(target.activeAppContext));
        throwIfAborted(abortController.signal);
        response = await createRuntimeSessionWithTurn({
          appReferences: message.appReferences,
          attachments: message.attachments,
          clientMessageId: message.clientMessageId,
          inputText: message.content,
          options: {
            agent_id: agentRuntimeConfig?.agent_id,
            agent_role_id: agentRuntimeConfig?.agent_role_id,
            agent_type_id: agentRuntimeConfig?.agent_type_id,
            project_id: targetDraftChat?.projectId ?? null,
            source_app_id: agentRuntimeConfig?.source_app_id || "chat",
            system_prompt: systemPrompt,
            skill_catalog_app_id: agentRuntimeConfig?.skill_catalog_app_id,
            skill_ids: agentRuntimeConfig?.skill_ids || [],
            runtime_mode: agentRuntimeConfig?.runtime_mode,
            routing_profile: agentRuntimeConfig?.routing_profile,
            hosted_provider_id: agentRuntimeConfig?.hosted_provider_id,
            hosted_model_id: agentRuntimeConfig?.hosted_model_id,
            title: "New chat",
          },
          signal: abortController.signal,
        });
      } else if (!hasTargetThread(target, thread)) {
        throw new Error("This chat no longer exists.");
      } else {
        if (!thread.runtime_session_id) {
          throw new Error("This chat does not have a runtime session.");
        }
        response = await sendRuntimeTurn(
          thread.runtime_session_id,
          message.content,
          message.clientMessageId,
          message.attachments,
          message.appReferences,
          { signal: abortController.signal },
        );
      }
      throwIfAborted(abortController.signal);
      const responseThread = response.thread;
      const baseThread = responseThread || thread;
      if (!baseThread) {
        throw new Error("Runtime thread was not created.");
      }
      const userMessageAt = response.turn.created_at || new Date().toISOString();
      const optimisticThread = {
        ...baseThread,
        ...(responseThread || {}),
        availability: response.turn.status === "queued" || response.turn.status === "active" ? response.turn.status : "free",
        last_user_message_at: userMessageAt,
      };
      const threadKey = threadConversationKey(optimisticThread.thread_id);
      migrateConversationState(conversationKey, threadKey);
      inFlightSubmissionsRef.current[threadKey] = {
        ...(inFlightSubmissionsRef.current[threadKey] || {
          abortController,
          clientMessageId: message.clientMessageId,
        }),
        turnId: response.turn.turn_id,
      };
      setSubmittedTurnForConversation(threadKey, response.turn.turn_id);
      setThreads((current) => upsertOrderedThread(current, optimisticThread));
      if (isConversationStillActive(conversationKey)) {
        setActiveSession(response.session);
        setActiveTurn(response.turn);
        setEvents((current) => mergeRuntimeEvents(current, response.events));
        setActiveThread((current) => (current?.thread_id === optimisticThread.thread_id ? { ...current, ...optimisticThread } : optimisticThread));
        if (!thread) {
          setDraftChat(null);
        }
      }
      if (!thread && isConversationStillActive(conversationKey)) {
        notifyActiveThreadChanged(optimisticThread.thread_id);
        openChatThreadRouteInShell(optimisticThread.thread_id, { navigationScope });
      }
      if (response.turn.status !== "queued" && response.turn.status !== "active") {
        removePendingMessage(threadKey, message.clientMessageId);
        setSubmittedTurnForConversation(threadKey, null);
      }
    } catch (sendError) {
      removePendingMessage(conversationKey, message.clientMessageId);
      setSubmittedTurnForConversation(conversationKey, null);
      if (!isAbortError(sendError)) {
        addFailedMessage(conversationKey, message);
        if (isConversationStillActive(conversationKey)) {
          setError(sendError instanceof Error ? sendError.message : "Unable to send message.");
          setActiveTurn(null);
          setComposer(message.content);
          setSelectedReferences(message.appReferences);
        }
      }
    } finally {
      if (!inFlightSubmissionsRef.current[conversationKey]?.turnId) {
        delete inFlightSubmissionsRef.current[conversationKey];
      }
      setConversationSending(conversationKey, false);
    }
  }

  async function submitInterAgentMessage(
    message: QueuedMessage,
    target: SubmissionTarget,
    signal: AbortSignal,
  ) {
    const conversationKey = target.conversationKey;
    const targetThread = target.thread;
    const targetDraftChat = target.draftChat;
    let thread = targetThread;
    let session: RuntimeSession | null = null;
    const agentRuntimeConfig = await selectedAgentRuntimeConfig(target.activeAppContext);
    throwIfAborted(signal);
    if (!thread) {
      const systemPrompt =
        agentRuntimeConfig?.system_prompt || targetDraftChat?.systemPrompt || (await loadDefaultSystemPrompt(target.activeAppContext));
      throwIfAborted(signal);
      session = await createRuntimeSession(
        {
          agent_id: agentRuntimeConfig?.agent_id,
          agent_role_id: agentRuntimeConfig?.agent_role_id,
          agent_type_id: agentRuntimeConfig?.agent_type_id,
          project_id: targetDraftChat?.projectId ?? null,
          source_app_id: agentRuntimeConfig?.source_app_id || "chat",
          system_prompt: systemPrompt,
          skill_catalog_app_id: agentRuntimeConfig?.skill_catalog_app_id,
          skill_ids: agentRuntimeConfig?.skill_ids || [],
          runtime_mode: agentRuntimeConfig?.runtime_mode,
          routing_profile: agentRuntimeConfig?.routing_profile,
          hosted_provider_id: agentRuntimeConfig?.hosted_provider_id,
          hosted_model_id: agentRuntimeConfig?.hosted_model_id,
          title: "New chat",
        },
        { signal },
      );
      const now = new Date().toISOString();
      thread = {
        thread_id: session.session_id,
        runtime_session_id: session.session_id,
        title: "New chat",
        title_pending: true,
        title_source: "pending",
        agent_label: agentRuntimeConfig?.agent_id || "chat",
        agent_type_id: agentRuntimeConfig?.agent_type_id || "",
        agent_role_id: agentRuntimeConfig?.agent_role_id || "",
        source_app_id: agentRuntimeConfig?.source_app_id || "chat",
        system_prompt: systemPrompt,
        project_id: targetDraftChat?.projectId ?? null,
        archived: false,
        availability: "queued",
        created_at: now,
        updated_at: now,
        last_user_message_at: now,
      };
    } else if (!hasTargetThread(target, thread)) {
      throw new Error("This chat no longer exists.");
    }
    if (!thread.runtime_session_id) {
      throw new Error("This chat does not have a runtime session.");
    }

    const runPlan = interAgentRunPlan({
      agentRuntimeConfig,
      mode: message.multiAgentMode || "auto",
      thread,
      clientMessageId: message.clientMessageId,
    });
    const runDetail = await createInterAgentRun(runPlan.payload, { signal });
    throwIfAborted(signal);
    if (isConversationStillActive(conversationKey)) {
      onInterAgentRunChanged?.(runDetail);
    }
    const executed = await executeInterAgentRun(runDetail.run.run_id, {
      input_text: message.content,
      client_message_id: message.clientMessageId,
      participant_inputs: runPlan.participantInputs,
      attachments: message.attachments,
      app_references: message.appReferences,
      async: true,
    }, { signal });
    throwIfAborted(signal);
    const userMessageAt = executed.root_runtime_turn?.created_at || new Date().toISOString();
    const availability =
      executed.root_runtime_turn?.status === "queued" || executed.root_runtime_turn?.status === "active" ? executed.root_runtime_turn.status : "free";
    const optimisticThread = {
      ...thread,
      availability,
      last_user_message_at: userMessageAt,
      updated_at: userMessageAt,
    };
    const threadKey = threadConversationKey(optimisticThread.thread_id);
    migrateConversationState(conversationKey, threadKey);
    if (executed.root_runtime_turn) {
      inFlightSubmissionsRef.current[threadKey] = {
        ...(inFlightSubmissionsRef.current[threadKey] || {
          abortController: inFlightSubmissionsRef.current[conversationKey]?.abortController || new AbortController(),
          clientMessageId: message.clientMessageId,
        }),
        turnId: executed.root_runtime_turn.turn_id,
      };
      setSubmittedTurnForConversation(threadKey, executed.root_runtime_turn.turn_id);
    }
    setThreads((current) => upsertOrderedThread(current, optimisticThread));
    if (isConversationStillActive(conversationKey)) {
      onInterAgentRunChanged?.(executed);
      if (session) {
        setActiveSession(session);
        setDraftChat(null);
      }
      if (executed.root_runtime_turn) {
        setActiveTurn(executed.root_runtime_turn);
      }
      if (executed.root_runtime_events?.length) {
        setEvents((current) => mergeRuntimeEvents(current, executed.root_runtime_events || []));
      }
      setActiveThread((current) => (current?.thread_id === optimisticThread.thread_id ? { ...current, ...optimisticThread } : optimisticThread));
    }
    if (!targetThread && isConversationStillActive(conversationKey)) {
      notifyActiveThreadChanged(optimisticThread.thread_id);
      openChatThreadRouteInShell(optimisticThread.thread_id, { navigationScope });
    }
    if (!executed.root_runtime_turn || (executed.root_runtime_turn.status !== "queued" && executed.root_runtime_turn.status !== "active")) {
      removePendingMessage(threadKey, message.clientMessageId);
      setSubmittedTurnForConversation(threadKey, null);
    }
  }

  async function handleSend() {
    const input = composer.trim();
    const targetAttachments = [...attachments];
    if ((!input && !targetAttachments.length) || hasInvalidAttachments(targetAttachments)) {
      return;
    }
    const target = currentSubmissionTarget();
    if (!target) {
      return;
    }
    const clientMessageId = crypto.randomUUID();
    const appReferences = mergeAppReferences(appReferencesFromText(input, composerMentionItems), target.activeAppContext);
    const localMessage: QueuedMessage = {
      clientMessageId,
      content: input,
      attachments: targetAttachments.map(attachmentToMessageAttachment),
      appReferences,
      multiAgentMode,
    };
    const shouldQueue = isRuntimeBusy || Boolean(sendingByConversationKey[target.conversationKey]);
    setComposerError(null);
    setComposer("");
    setSelectedReferences([]);
    clearAttachments();
    if (shouldQueue) {
      let messageAttachments;
      try {
        messageAttachments = await Promise.all(targetAttachments.map(uploadComposerAttachment));
      } catch (uploadError) {
        if (isConversationStillActive(resolveConversationKeyAlias(target.conversationKey))) {
          setComposerError(uploadError instanceof Error ? uploadError.message : "Unable to upload attachments.");
          setComposer(input);
          setSelectedReferences(appReferences);
        }
        return;
      }
      const queueConversationKey = resolveConversationKeyAlias(target.conversationKey);
      setItemsForConversation(setQueuedMessagesByConversationKey, queueConversationKey, (current) => [
        ...current,
        { clientMessageId, content: input, attachments: messageAttachments, appReferences, multiAgentMode },
      ]);
      return;
    }
    const abortController = startSubmission(target, localMessage);
    try {
      const message = {
        ...localMessage,
        attachments: await uploadAttachmentsWithAbort(targetAttachments, abortController.signal),
      };
      replacePendingMessage(target.conversationKey, message);
      await submitMessage(message, target, abortController);
    } catch (uploadError) {
      clearSubmission(target, clientMessageId);
      if (!isAbortError(uploadError)) {
        addFailedMessage(target.conversationKey, localMessage);
        if (isConversationStillActive(target.conversationKey)) {
          setComposerError(uploadError instanceof Error ? uploadError.message : "Unable to upload attachments.");
          setComposer(input);
          setSelectedReferences(appReferences);
        }
      }
    }
  }

  useEffect(() => {
    if (isBootstrapping || isHistoryLoading || isRuntimeBusy || isSending || queuedMessages.length === 0 || !activeConversationKey) {
      return;
    }
    const target = currentSubmissionTarget(activeConversationKey);
    if (!target) {
      return;
    }
    const [nextMessage, ...remainingMessages] = queuedMessages;
    setQueuedMessages(remainingMessages);
    const abortController = startSubmission(target, nextMessage);
    void submitMessage(nextMessage, target, abortController);
  }, [activeConversationKey, isBootstrapping, isHistoryLoading, isRuntimeBusy, isSending, queuedMessages]);

  useEffect(() => {
    if (!activeConversationKey || isRuntimeBusy) {
      return;
    }
    const inFlightSubmission = inFlightSubmissionsRef.current[activeConversationKey];
    if (inFlightSubmission?.turnId) {
      delete inFlightSubmissionsRef.current[activeConversationKey];
      setSubmittedTurnForConversation(activeConversationKey, null);
    }
  }, [activeConversationKey, isRuntimeBusy]);

  return {
    activeSubmissionTurnId,
    failedUserMessages,
    handleSend,
    isSending,
    pendingUserMessages,
    queuedMessages,
    setFailedUserMessages,
    setFailedUserMessagesForConversation,
    setPendingUserMessages,
    setPendingUserMessagesForConversation,
    setQueuedMessages,
    setQueuedMessagesForConversation,
    stopActiveSubmission,
  };
}

export function interAgentRunPayload({
  agentRuntimeConfig,
  clientMessageId,
  mode,
  thread,
}: {
  agentRuntimeConfig: AgentRuntimeConfig | null;
  clientMessageId: string;
  mode: MultiAgentComposerMode;
  thread: ChatThread;
}) {
  return interAgentRunPlan({ agentRuntimeConfig, clientMessageId, mode, thread }).payload;
}

export function interAgentRunParticipantInputs({
  agentRuntimeConfig,
  clientMessageId,
  mode,
  thread,
}: {
  agentRuntimeConfig: AgentRuntimeConfig | null;
  clientMessageId: string;
  mode: MultiAgentComposerMode;
  thread: ChatThread;
}): Record<string, string> {
  return interAgentRunPlan({ agentRuntimeConfig, clientMessageId, mode, thread }).participantInputs || {};
}

export function interAgentComposerBudgetLabel(mode: MultiAgentComposerMode): string {
  if (mode === "off") {
    return "";
  }
  const budget = interAgentBudget(mode);
  const workerCount = interAgentWorkerPlans(mode).length;
  return [
    pluralLabel(workerCount, "worker"),
    pluralLabel(budget.max_total_turns, "turn"),
    pluralLabel(budget.max_tool_calls, "tool call"),
  ].join(" · ");
}

function interAgentRunPlan({
  agentRuntimeConfig,
  clientMessageId,
  mode,
  thread,
}: {
  agentRuntimeConfig: AgentRuntimeConfig | null;
  clientMessageId: string;
  mode: MultiAgentComposerMode;
  thread: ChatThread;
}): { payload: CreateInterAgentRunPayload; participantInputs?: Record<string, string> } {
  const participantLabel = agentRuntimeConfig?.title || thread.agent_label || "Maverick agent";
  const agentTypeId = agentRuntimeConfig?.agent_type_id || thread.agent_type_id || "";
  const workerPlans = interAgentWorkerPlans(mode);
  const participants: InterAgentParticipantSpecPayload[] = [
    {
      participant_id: "orchestrator",
      kind: "orchestrator",
      execution_mode: "root_orchestrator",
      label: "Orchestrator",
    },
    ...workerPlans.map((worker) =>
      interAgentWorkerParticipant({
        agentRuntimeConfig,
        agentTypeId,
        fallbackLabel: participantLabel,
        worker,
      }),
    ),
  ];
  return {
    payload: {
      thread_id: thread.thread_id,
      root_runtime_session_id: thread.runtime_session_id,
      mode: interAgentRunMode(mode),
      idempotency_key: `chat:${clientMessageId}:${mode}`,
      ...(mode === "group_chat" ? { aggregator_participant_id: "synthesizer" } : {}),
      visibility_level: "detail",
      participants,
      edges: interAgentEdges(mode, participantLabel),
      budget: interAgentBudget(mode),
    },
    participantInputs:
      mode === "multi" || mode === "group_chat"
        ? Object.fromEntries(workerPlans.map((worker) => [worker.participantId, worker.task]))
        : undefined,
  };
}

function interAgentRunMode(mode: MultiAgentComposerMode): CreateInterAgentRunPayload["mode"] {
  if (mode === "multi") {
    return "sequential";
  }
  if (mode === "group_chat") {
    return "group_chat";
  }
  return "manager_tools";
}

function interAgentWorkerParticipant({
  agentRuntimeConfig,
  agentTypeId,
  fallbackLabel,
  worker,
}: {
  agentRuntimeConfig: AgentRuntimeConfig | null;
  agentTypeId: string;
  fallbackLabel: string;
  worker: InterAgentWorkerPlan;
}): InterAgentParticipantSpecPayload {
  const agentSnapshot =
    agentRuntimeConfig?.agent_type_id
      ? {
          agent_type_id: agentRuntimeConfig.agent_type_id,
          label: worker.label || fallbackLabel,
          system_prompt: agentRuntimeConfig.system_prompt || "",
          skill_ids: agentRuntimeConfig.skill_ids || [],
          skill_catalog_app_id: agentRuntimeConfig.skill_catalog_app_id || "skills",
        }
      : undefined;
  return {
    participant_id: worker.participantId,
    kind: "agent",
    execution_mode: "child_runtime_session",
    label: worker.label || fallbackLabel,
    ...(agentTypeId ? { agent_type_id: agentTypeId } : {}),
    ...(agentSnapshot ? { agent_snapshot: agentSnapshot } : {}),
  };
}

function interAgentWorkerPlans(mode: MultiAgentComposerMode): InterAgentWorkerPlan[] {
  if (mode === "group_chat") {
    return [
      {
        participantId: "analyst",
        label: "Analyst",
        task:
          "Analyze the request and contribute the strongest direct answer, evidence, or implementation direction. " +
          "Do not mention internal workers, routing, orchestration, or group-chat mechanics.",
      },
      {
        participantId: "reviewer",
        label: "Reviewer",
        task:
          "Review the request and prior contribution for gaps, risks, or corrections. " +
          "Return only user-facing improvements or corrections, without narrating internal review mechanics.",
      },
      {
        participantId: "synthesizer",
        label: "Synthesizer",
        task:
          "Synthesize the group chat contributions into the final user-facing answer. " +
          "Do not mention participants, internal workers, routing, orchestration, or group-chat mechanics.",
      },
    ];
  }
  if (mode === "multi") {
    return [
      {
        participantId: "implementer",
        label: "Implementer",
        task:
          "Produce the concrete user-facing answer or implementation plan for the request. " +
          "Treat any wording about worker counts, reviewers, orchestrators, handoffs, routing, or multi-agent setup as Maverick control context. " +
          "Do not mention internal workers or orchestration in the answer.",
      },
      {
        participantId: "reviewer",
        label: "Reviewer",
        task:
          "Review the implementer's output against the user request, then return one orchestrator-ready final answer. " +
          "If the output is correct, return the polished answer. If it has gaps, return the corrected final answer. " +
          "Do not narrate the review process or mention internal workers, reviewers, handoffs, routing, or orchestration.",
      },
    ];
  }
  return [
    {
      participantId: "assistant",
      label: "",
      task: "",
    },
  ];
}

function interAgentEdges(mode: MultiAgentComposerMode, participantLabel: string): CreateInterAgentRunPayload["edges"] {
  if (mode === "group_chat") {
    return [
      {
        source_id: "orchestrator",
        target_id: "analyst",
        kind: "delegated",
        label: "Analysis",
      },
      {
        source_id: "orchestrator",
        target_id: "reviewer",
        kind: "delegated",
        label: "Review",
      },
      {
        source_id: "analyst",
        target_id: "synthesizer",
        kind: "depends_on",
        label: "Contribution",
      },
      {
        source_id: "reviewer",
        target_id: "synthesizer",
        kind: "depends_on",
        label: "Correction",
      },
      {
        source_id: "synthesizer",
        target_id: "orchestrator",
        kind: "produced",
        label: "Final synthesis",
      },
    ];
  }
  if (mode === "multi") {
    return [
      {
        source_id: "orchestrator",
        target_id: "implementer",
        kind: "delegated",
        label: "Implementation",
      },
      {
        source_id: "implementer",
        target_id: "reviewer",
        kind: "reviewed_by",
        label: "Review",
      },
      {
        source_id: "reviewer",
        target_id: "orchestrator",
        kind: "produced",
        label: "Final review",
      },
    ];
  }
  return [
    {
      source_id: "orchestrator",
      target_id: "assistant",
      kind: "delegated",
      label: participantLabel,
    },
  ];
}

function interAgentBudget(mode: MultiAgentComposerMode): CreateInterAgentRunPayload["budget"] {
  if (mode === "group_chat") {
    return {
      max_participants: 4,
      max_concurrent_participants: 1,
      max_rounds: 1,
      max_total_turns: 3,
      max_turns_per_participant: 1,
      max_tool_calls: 3,
    };
  }
  if (mode === "multi") {
    return {
      max_participants: 3,
      max_concurrent_participants: 1,
      max_total_turns: 2,
      max_turns_per_participant: 1,
      max_tool_calls: 2,
    };
  }
  return {
    max_participants: 2,
    max_concurrent_participants: 1,
    max_total_turns: 1,
    max_turns_per_participant: 1,
    max_tool_calls: 1,
  };
}

function pluralLabel(count: number, singular: string): string {
  return `${count} ${singular}${count === 1 ? "" : "s"}`;
}
