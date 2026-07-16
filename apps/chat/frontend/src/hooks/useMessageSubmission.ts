import { Dispatch, SetStateAction, useCallback, useEffect, useRef, useState } from "react";
import {
  AppReference,
  ChatThread,
  InterAgentRunDetail,
  MultiAgentComposerMode,
  RuntimeEvent,
  RuntimeSession,
  RuntimeTurn,
  RuntimeTurnSubmitResponse,
  type CreateInterAgentRunPayload,
  type InterAgentParticipantSpecPayload,
  createInterAgentRun,
  createRuntimeSession,
  createRuntimeSessionWithTurn,
  executeInterAgentRun,
  interruptRuntimeTurn,
  isRuntimeSessionUnavailableError,
  prepareRuntimeSessionAppReferences,
  prewarmRuntimeSession,
  recordRuntimeTurnClientMetrics,
  sendRuntimeTurn,
} from "../api/client";
import type { ComposerAttachment } from "../lib/attachments";
import type { RuntimeSessionOptions, RuntimeTurnClientMetrics } from "../api/client";
import { hasInvalidAttachments } from "../lib/attachments";
import { ActiveAppContext, mergeAppReferences } from "../lib/activeAppContext";
import { appReferencesFromText } from "../lib/mentions";
import type { MentionItem } from "../lib/mentions";
import {
  PendingMessage,
  QueuedMessage,
  attachmentToMessageAttachment,
  composerAttachmentsUploadSnapshot,
  uploadComposerAttachment,
} from "../lib/messageState";
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
  canPreloadRuntime: boolean;
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

type PreparedRuntimeSession = {
  conversationKey: string;
  key: string;
  session: RuntimeSession;
};

type PreparedRuntimeSessionRequest = {
  abortController: AbortController;
  conversationKey: string;
  key: string;
  promise: Promise<PreparedRuntimeSession | null>;
};

type PreparedAppReferencesRequest = {
  abortController: AbortController;
  key: string;
  sessionId: string;
  promise: Promise<void>;
};

type PreparedRuntimeSessionLookup = {
  key: string;
  prepared: PreparedRuntimeSession | null;
  readyBeforeSubmit: boolean;
  waitOnSubmitMs: number;
};

const PREPARED_RUNTIME_SESSION_SUBMIT_WAIT_MS = 200;
const PREPARED_RUNTIME_SESSION_PLAIN_SUBMIT_WAIT_MS = 350;
const PREPARED_APP_REFERENCES_SUBMIT_WAIT_MS = 200;
const NEW_CHAT_PRELOAD_CONVERSATION_KEY = "draft:active";

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

function optimisticThreadForPendingSession({
  agentRuntimeConfig,
  draftChat,
  messageCreatedAt,
  session,
  systemPrompt,
}: {
  agentRuntimeConfig: AgentRuntimeConfig | null;
  draftChat: DraftChat | null;
  messageCreatedAt: string;
  session: RuntimeSession;
  systemPrompt: string;
}): ChatThread {
  return {
    thread_id: session.session_id,
    runtime_session_id: session.session_id,
    title: "New chat",
    title_pending: true,
    title_source: "pending",
    agent_label: agentRuntimeConfig?.agent_id || session.agent_id || "chat",
    agent_type_id: agentRuntimeConfig?.agent_type_id || "",
    agent_role_id: agentRuntimeConfig?.agent_role_id || "",
    source_app_id: agentRuntimeConfig?.source_app_id || session.agent_id || "chat",
    system_prompt: systemPrompt,
    project_id: draftChat?.projectId ?? null,
    archived: false,
    availability: "queued",
    created_at: messageCreatedAt,
    updated_at: messageCreatedAt,
    last_user_message_at: messageCreatedAt,
    runtime_mode: session.runtime_mode,
    provider_id: session.provider_id,
    hosted_provider_id: session.hosted_provider_id,
    hosted_model_id: session.hosted_model_id,
  };
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

function isPendingIdempotencyResponse(response: RuntimeTurnSubmitResponse): boolean {
  return response.idempotency?.status === "pending" && !response.turn;
}

function runtimeSessionOptionsForNewChat({
  agentRuntimeConfig,
  draftChat,
  systemPrompt,
}: {
  agentRuntimeConfig: AgentRuntimeConfig | null;
  draftChat: DraftChat | null;
  systemPrompt: string;
}): RuntimeSessionOptions {
  return {
    agent_id: agentRuntimeConfig?.agent_id,
    agent_role_id: agentRuntimeConfig?.agent_role_id,
    agent_type_id: agentRuntimeConfig?.agent_type_id,
    project_id: draftChat?.projectId ?? null,
    source_app_id: agentRuntimeConfig?.source_app_id || "chat",
    system_prompt: systemPrompt,
    skill_catalog_app_id: agentRuntimeConfig?.skill_catalog_app_id,
    skill_ids: agentRuntimeConfig?.skill_ids || [],
    runtime_mode: agentRuntimeConfig?.runtime_mode,
    routing_profile: agentRuntimeConfig?.routing_profile,
    hosted_provider_id: agentRuntimeConfig?.hosted_provider_id,
    hosted_model_id: agentRuntimeConfig?.hosted_model_id,
    title: "New chat",
  };
}

function preparedRuntimeSessionKey(conversationKey: string, options: RuntimeSessionOptions): string {
  return JSON.stringify({
    conversationKey,
    agent_id: options.agent_id || "chat",
    agent_role_id: options.agent_role_id || "",
    agent_type_id: options.agent_type_id || "",
    hosted_model_id: options.hosted_model_id || "",
    hosted_provider_id: options.hosted_provider_id || "",
    project_id: options.project_id || null,
    routing_profile: options.routing_profile || "",
    runtime_mode: options.runtime_mode || "",
    skill_catalog_app_id: options.skill_catalog_app_id || "",
    skill_ids: options.skill_ids || [],
    source_app_id: options.source_app_id || "chat",
    system_prompt: options.system_prompt || "",
  });
}

function stableJson(value: unknown): string {
  if (Array.isArray(value)) {
    return `[${value.map(stableJson).join(",")}]`;
  }
  if (value && typeof value === "object") {
    const record = value as Record<string, unknown>;
    return `{${Object.keys(record)
      .sort()
      .map((key) => `${JSON.stringify(key)}:${stableJson(record[key])}`)
      .join(",")}}`;
  }
  return JSON.stringify(value) ?? "null";
}

function preparedAppReferencesKey(sessionId: string, appReferences: AppReference[]): string {
  return stableJson({ app_references: appReferences, session_id: sessionId });
}

function elapsedMs(startedAt: number): number {
  return Math.max(0, performance.now() - startedAt);
}

function preparedRuntimeSessionSubmitWaitMs(message: QueuedMessage): number {
  if (!message.appReferences.length && !message.attachments.length) {
    return PREPARED_RUNTIME_SESSION_PLAIN_SUBMIT_WAIT_MS;
  }
  return PREPARED_RUNTIME_SESSION_SUBMIT_WAIT_MS;
}

function turnIdForSubmitResponse(response: RuntimeTurnSubmitResponse | null): string {
  return response?.turn?.turn_id || response?.idempotency?.turn_id || "";
}

export function useMessageSubmission({
  activeAppContext,
  activeThread,
  attachments,
  clearAttachments,
  composer,
  composerMentionItems,
  draftChat,
  canPreloadRuntime,
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
  const preparedRuntimeSessionRef = useRef<PreparedRuntimeSession | null>(null);
  const preparedRuntimeSessionRequestRef = useRef<PreparedRuntimeSessionRequest | null>(null);
  const preparedAppReferencesRequestRef = useRef<PreparedAppReferencesRequest | null>(null);
  const activeThreadPrewarmRef = useRef("");
  const [pendingUserMessagesByConversationKey, setPendingUserMessagesByConversationKey] = useState<ConversationItems<PendingMessage>>({});
  const [failedUserMessagesByConversationKey, setFailedUserMessagesByConversationKey] = useState<ConversationItems<PendingMessage>>({});
  const [queuedMessagesByConversationKey, setQueuedMessagesByConversationKey] = useState<ConversationItems<QueuedMessage>>({});
  const [sendingByConversationKey, setSendingByConversationKey] = useState<Record<string, true>>({});
  const [submittedTurnByConversationKey, setSubmittedTurnByConversationKey] = useState<Record<string, string>>({});
  const isRuntimeBusyRef = useRef(isRuntimeBusy);
  const sendingByConversationKeyRef = useRef(sendingByConversationKey);
  const pendingUserMessages = itemsForConversation(pendingUserMessagesByConversationKey, activeConversationKey);
  const failedUserMessages = itemsForConversation(failedUserMessagesByConversationKey, activeConversationKey);
  const queuedMessages = itemsForConversation(queuedMessagesByConversationKey, activeConversationKey);
  const isSending = Boolean(activeConversationKey && sendingByConversationKey[activeConversationKey]);
  const activeSubmissionTurnId = activeConversationKey ? submittedTurnByConversationKey[activeConversationKey] || "" : "";

  useEffect(() => {
    isRuntimeBusyRef.current = isRuntimeBusy;
    sendingByConversationKeyRef.current = sendingByConversationKey;
  }, [isRuntimeBusy, sendingByConversationKey]);

  useEffect(() => {
    activeConversationKeyRef.current = activeConversationKey;
    activeAppContextRef.current = activeAppContext;
    activeThreadRef.current = activeThread;
    draftChatRef.current = draftChat;
    threadsRef.current = threads;
  }, [activeAppContext, activeConversationKey, activeThread, draftChat, threads]);

  useEffect(() => {
    const preloadConversationKey = !activeThread ? NEW_CHAT_PRELOAD_CONVERSATION_KEY : "";
    if (activeThread || !canPreloadRuntime || !preloadConversationKey) {
      return;
    }
    const target: SubmissionTarget = {
      activeAppContext,
      conversationKey: preloadConversationKey,
      draftChat,
      thread: null,
      threadIds: new Set(threads.map((item) => item.thread_id)),
    };
    void buildRuntimeSessionOptions(target)
      .then(({ options }) => {
        const key = preparedRuntimeSessionKey(preloadConversationKey, options);
        if (preparedRuntimeSessionRef.current?.key === key || preparedRuntimeSessionRequestRef.current?.key === key) {
          return;
        }
        requestPreparedRuntimeSession(preloadConversationKey, key, options);
      })
      .catch(() => undefined);
  }, [activeAppContext, activeConversationKey, activeThread, canPreloadRuntime, draftChat, selectedAgentRuntimeConfig, threads]);

  useEffect(() => {
    const runtimeSessionId = activeThread?.runtime_session_id || "";
    if (!runtimeSessionId || !canPreloadRuntime || isRuntimeBusy) {
      return;
    }
    if (activeThreadPrewarmRef.current === runtimeSessionId) {
      return;
    }
    activeThreadPrewarmRef.current = runtimeSessionId;
    const abortController = new AbortController();
    void prewarmRuntimeSession(runtimeSessionId, { signal: abortController.signal }).catch((error) => {
      if (!isAbortError(error) && activeThreadPrewarmRef.current === runtimeSessionId) {
        activeThreadPrewarmRef.current = "";
      }
    });
    return () => {
      abortController.abort();
    };
  }, [activeThread?.runtime_session_id, canPreloadRuntime, isRuntimeBusy]);

  useEffect(() => {
    if (isBootstrapping || (!activeThread && (!draftChat || !activeConversationKey))) {
      cancelPreparedAppReferencesRequest();
      return;
    }
    const input = composer.trim();
    if (!input) {
      return;
    }
    const appReferences = mergeAppReferences(appReferencesFromText(input, composerMentionItems), activeAppContext);
    if (!appReferences.length) {
      return;
    }
    const target: SubmissionTarget = {
      activeAppContext,
      conversationKey: activeConversationKey,
      draftChat,
      thread: null,
      threadIds: new Set(threads.map((item) => item.thread_id)),
    };
    const abortController = new AbortController();
    const prepareDelayMs = appReferences.some((reference) => reference.app_id === "storage") ? 0 : 300;
    const timeout = window.setTimeout(() => {
      if (activeThread?.runtime_session_id) {
        startPreparedAppReferencesRequest(activeThread.runtime_session_id, appReferences);
        return;
      }
      void buildRuntimeSessionOptions(target, abortController.signal)
        .then(({ options }) => {
          throwIfAborted(abortController.signal);
          const key = preparedRuntimeSessionKey(NEW_CHAT_PRELOAD_CONVERSATION_KEY, options);
          const prepared = preparedRuntimeSessionRef.current;
          if (prepared?.key === key) {
            startPreparedAppReferencesRequest(prepared.session.session_id, appReferences);
            return null;
          }
          const pending = preparedRuntimeSessionRequestRef.current;
          if (pending?.key === key) {
            return waitForPreparedRuntimeSession(pending, abortController.signal);
          }
          return requestPreparedRuntimeSession(NEW_CHAT_PRELOAD_CONVERSATION_KEY, key, options);
        })
        .then((prepared) => {
          throwIfAborted(abortController.signal);
          if (prepared) {
            startPreparedAppReferencesRequest(prepared.session.session_id, appReferences);
          }
        })
        .catch((error) => {
          void error;
        });
    }, prepareDelayMs);
    return () => {
      window.clearTimeout(timeout);
      abortController.abort();
    };
  }, [
    activeAppContext,
    activeConversationKey,
    activeThread,
    composer,
    composerMentionItems,
    draftChat,
    isBootstrapping,
    selectedAgentRuntimeConfig,
    threads,
  ]);

  useEffect(() => {
    attachments.forEach((attachment) => {
      if (attachment.isImage && !attachment.warning) {
        void uploadComposerAttachment(attachment).catch(() => undefined);
      }
    });
  }, [attachments]);

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
              multiAgentMode: message.multiAgentMode,
              clientSubmissionStartedAt: message.clientSubmissionStartedAt,
              clientSubmissionMetrics: message.clientSubmissionMetrics,
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
        multiAgentMode: message.multiAgentMode,
        clientSubmissionStartedAt: message.clientSubmissionStartedAt,
        clientSubmissionMetrics: message.clientSubmissionMetrics,
      },
    ]);
  }

  async function buildRuntimeSessionOptions(
    target: SubmissionTarget,
    signal?: AbortSignal,
  ): Promise<{
    agentRuntimeConfig: AgentRuntimeConfig | null;
    options: RuntimeSessionOptions;
    systemPrompt: string;
  }> {
    if (signal) {
      throwIfAborted(signal);
    }
    const agentRuntimeConfigPromise = selectedAgentRuntimeConfig(target.activeAppContext);
    const defaultSystemPromptPromise = target.draftChat?.systemPrompt
      ? Promise.resolve(target.draftChat.systemPrompt)
      : loadDefaultSystemPrompt(target.activeAppContext);
    const [agentRuntimeConfig, defaultSystemPrompt] = await Promise.all([
      agentRuntimeConfigPromise,
      defaultSystemPromptPromise,
    ]);
    if (signal) {
      throwIfAborted(signal);
    }
    const systemPrompt = agentRuntimeConfig?.system_prompt || target.draftChat?.systemPrompt || defaultSystemPrompt;
    if (signal) {
      throwIfAborted(signal);
    }
    return {
      agentRuntimeConfig,
      options: runtimeSessionOptionsForNewChat({
        agentRuntimeConfig,
        draftChat: target.draftChat,
        systemPrompt,
      }),
      systemPrompt,
    };
  }

  function requestPreparedRuntimeSession(
    conversationKey: string,
    key: string,
    options: RuntimeSessionOptions,
  ): Promise<PreparedRuntimeSession | null> {
    const existing = preparedRuntimeSessionRequestRef.current;
    if (existing?.key === key) {
      return existing.promise;
    }
    if (existing) {
      existing.abortController.abort();
    }
    const abortController = new AbortController();
    const promise = createRuntimeSession(
      {
        ...options,
        prepare_only: true,
      },
      { signal: abortController.signal },
    )
      .then((session) => {
        if (!session.prewarm_completed || !session.provider_thread_ready) {
          return null;
        }
        const prepared = { conversationKey, key, session };
        if (preparedRuntimeSessionRequestRef.current?.key === key) {
          preparedRuntimeSessionRef.current = prepared;
        }
        return prepared;
      })
      .catch((error) => {
        if (isAbortError(error)) {
          return null;
        }
        if (preparedRuntimeSessionRequestRef.current?.key === key) {
          preparedRuntimeSessionRef.current = null;
        }
        return null;
      })
      .finally(() => {
        if (preparedRuntimeSessionRequestRef.current?.key === key) {
          preparedRuntimeSessionRequestRef.current = null;
        }
      });
    preparedRuntimeSessionRequestRef.current = {
      abortController,
      conversationKey,
      key,
      promise,
    };
    return promise;
  }

  async function waitForPreparedRuntimeSession(
    request: PreparedRuntimeSessionRequest,
    signal: AbortSignal,
    timeoutMs = 0,
  ): Promise<PreparedRuntimeSession | null> {
    throwIfAborted(signal);
    return new Promise((resolve, reject) => {
      let settled = false;
      let timer: number | undefined;
      const cleanup = () => {
        signal.removeEventListener("abort", abort);
        if (timer !== undefined) {
          window.clearTimeout(timer);
        }
      };
      const finish = (action: () => void) => {
        if (settled) {
          return;
        }
        settled = true;
        cleanup();
        action();
      };
      const abort = () => finish(() => reject(abortError()));
      signal.addEventListener("abort", abort, { once: true });
      if (timeoutMs > 0) {
        timer = window.setTimeout(() => finish(() => resolve(null)), timeoutMs);
      }
      void request.promise.then(
        (prepared) => finish(() => resolve(prepared)),
        (error) => finish(() => reject(error)),
      );
    });
  }

  async function preparedRuntimeSessionForOptions(
    conversationKey: string,
    options: RuntimeSessionOptions,
    signal: AbortSignal,
    timeoutMs: number,
  ): Promise<PreparedRuntimeSessionLookup> {
    const preparedConversationKey = conversationKey.startsWith("draft:")
      ? NEW_CHAT_PRELOAD_CONVERSATION_KEY
      : conversationKey;
    const key = preparedRuntimeSessionKey(preparedConversationKey, options);
    const prepared = preparedRuntimeSessionRef.current;
    if (prepared?.key === key) {
      return {
        key,
        prepared,
        readyBeforeSubmit: true,
        waitOnSubmitMs: 0,
      };
    }
    const pending = preparedRuntimeSessionRequestRef.current;
    if (pending?.key === key) {
      if (timeoutMs <= 0) {
        return {
          key,
          prepared: null,
          readyBeforeSubmit: false,
          waitOnSubmitMs: 0,
        };
      }
      const startedAt = performance.now();
      const pendingPrepared = await waitForPreparedRuntimeSession(pending, signal, timeoutMs);
      return {
        key,
        prepared: pendingPrepared,
        readyBeforeSubmit: false,
        waitOnSubmitMs: elapsedMs(startedAt),
      };
    }
    return {
      key,
      prepared: null,
      readyBeforeSubmit: false,
      waitOnSubmitMs: 0,
    };
  }

  function forgetPreparedRuntimeSession(prepared: PreparedRuntimeSession | null) {
    if (!prepared) {
      return;
    }
    if (preparedAppReferencesRequestRef.current?.sessionId === prepared.session.session_id) {
      cancelPreparedAppReferencesRequest();
    }
    if (preparedRuntimeSessionRef.current?.key === prepared.key) {
      preparedRuntimeSessionRef.current = null;
    }
  }

  function cancelPreparedAppReferencesRequest() {
    const pending = preparedAppReferencesRequestRef.current;
    if (pending) {
      pending.abortController.abort();
      preparedAppReferencesRequestRef.current = null;
    }
  }

  function startPreparedAppReferencesRequest(sessionId: string, appReferences: AppReference[]): PreparedAppReferencesRequest | null {
    if (!appReferences.length) {
      cancelPreparedAppReferencesRequest();
      return null;
    }
    const key = preparedAppReferencesKey(sessionId, appReferences);
    const existing = preparedAppReferencesRequestRef.current;
    if (existing?.key === key) {
      return existing;
    }
    cancelPreparedAppReferencesRequest();
    const abortController = new AbortController();
    const request: PreparedAppReferencesRequest = {
      abortController,
      key,
      sessionId,
      promise: prepareRuntimeSessionAppReferences(sessionId, appReferences, { signal: abortController.signal })
        .then(() => undefined)
        .catch((error) => {
          if (!isAbortError(error)) {
            return undefined;
          }
          return undefined;
        })
        .finally(() => {
          if (preparedAppReferencesRequestRef.current?.key === key) {
            preparedAppReferencesRequestRef.current = null;
          }
        }),
    };
    preparedAppReferencesRequestRef.current = request;
    return request;
  }

  async function waitForPreparedAppReferencesRequest(
    request: PreparedAppReferencesRequest,
    signal: AbortSignal,
    timeoutMs: number,
  ): Promise<boolean> {
    throwIfAborted(signal);
    return new Promise((resolve, reject) => {
      let settled = false;
      let timer: number | undefined;
      const cleanup = () => {
        signal.removeEventListener("abort", abort);
        if (timer !== undefined) {
          window.clearTimeout(timer);
        }
      };
      const finish = (action: () => void) => {
        if (settled) {
          return;
        }
        settled = true;
        cleanup();
        action();
      };
      const abort = () => finish(() => reject(abortError()));
      signal.addEventListener("abort", abort, { once: true });
      if (timeoutMs > 0) {
        timer = window.setTimeout(() => finish(() => resolve(false)), timeoutMs);
      }
      void request.promise.then(
        () => finish(() => resolve(true)),
        () => finish(() => resolve(false)),
      );
    });
  }

  async function prepareAppReferencesForSubmit(sessionId: string, appReferences: AppReference[], signal: AbortSignal): Promise<number> {
    const request = startPreparedAppReferencesRequest(sessionId, appReferences);
    if (!request) {
      return 0;
    }
    const startedAt = performance.now();
    await waitForPreparedAppReferencesRequest(request, signal, PREPARED_APP_REFERENCES_SUBMIT_WAIT_MS);
    return elapsedMs(startedAt);
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
        multiAgentMode: message.multiAgentMode,
        clientSubmissionStartedAt: message.clientSubmissionStartedAt,
        clientSubmissionMetrics: message.clientSubmissionMetrics,
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

  function recordAttachmentUploadMetrics(
    metrics: RuntimeTurnClientMetrics,
    attachmentsToUpload: ComposerAttachment[],
    readyBeforeSubmit: boolean,
    waitOnSubmitMs: number,
  ) {
    const completed = composerAttachmentsUploadSnapshot(attachmentsToUpload);
    metrics.attachment_upload_ready_before_submit = readyBeforeSubmit;
    metrics.attachment_upload_wait_on_submit_ms = waitOnSubmitMs;
    if (typeof completed.uploadMs === "number") {
      metrics.attachment_upload_ms = completed.uploadMs;
    }
  }

  async function submitWithPostMetric<T>(metrics: RuntimeTurnClientMetrics, action: () => Promise<T>): Promise<T> {
    const startedAt = performance.now();
    try {
      return await action();
    } finally {
      metrics.submit_post_ms = elapsedMs(startedAt);
    }
  }

  function recordSubmitPostMetric(response: RuntimeTurnSubmitResponse | null, metrics: RuntimeTurnClientMetrics) {
    const turnId = turnIdForSubmitResponse(response);
    if (!turnId || typeof metrics.submit_post_ms !== "number") {
      return;
    }
    void recordRuntimeTurnClientMetrics(turnId, metrics).catch(() => undefined);
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
      let agentRuntimeConfig: AgentRuntimeConfig | null = null;
      let systemPrompt = targetDraftChat?.systemPrompt || "";
      let response: RuntimeTurnSubmitResponse | null = null;
      const clientMetrics: RuntimeTurnClientMetrics = { ...(message.clientSubmissionMetrics || {}) };
      if (!thread) {
        const runtimeOptions = await buildRuntimeSessionOptions(target, abortController.signal);
        agentRuntimeConfig = runtimeOptions.agentRuntimeConfig;
        systemPrompt = runtimeOptions.systemPrompt;
        const preparedLookup = await preparedRuntimeSessionForOptions(
          target.conversationKey,
          runtimeOptions.options,
          abortController.signal,
          preparedRuntimeSessionSubmitWaitMs(message),
        );
        clientMetrics.prepared_session_ready_before_submit = preparedLookup.readyBeforeSubmit;
        clientMetrics.prepared_session_wait_on_submit_ms = preparedLookup.waitOnSubmitMs;
        const prepared = preparedLookup.prepared;
        if (prepared) {
          try {
            clientMetrics.prepare_refs_wait_on_submit_ms = await prepareAppReferencesForSubmit(
              prepared.session.session_id,
              message.appReferences,
              abortController.signal,
            );
            response = await submitWithPostMetric(clientMetrics, () =>
              sendRuntimeTurn(
                prepared.session.session_id,
                message.content,
                message.clientMessageId,
                message.attachments,
                message.appReferences,
                {
                  signal: abortController.signal,
                  clientMetrics,
                  clientSubmissionStartedAt: message.clientSubmissionStartedAt,
                },
              ),
            );
            forgetPreparedRuntimeSession(prepared);
          } catch (sendPreparedError) {
            forgetPreparedRuntimeSession(prepared);
            if (!isRuntimeSessionUnavailableError(sendPreparedError, prepared.session.session_id)) {
              throw sendPreparedError;
            }
            response = await submitWithPostMetric(clientMetrics, () =>
              createRuntimeSessionWithTurn({
                appReferences: message.appReferences,
                attachments: message.attachments,
                clientMetrics,
                clientSubmissionStartedAt: message.clientSubmissionStartedAt,
                clientMessageId: message.clientMessageId,
                inputText: message.content,
                options: runtimeOptions.options,
                signal: abortController.signal,
              }),
            );
          }
        } else {
          clientMetrics.prepare_refs_wait_on_submit_ms = 0;
          response = await submitWithPostMetric(clientMetrics, () =>
            createRuntimeSessionWithTurn({
              appReferences: message.appReferences,
              attachments: message.attachments,
              clientMetrics,
              clientSubmissionStartedAt: message.clientSubmissionStartedAt,
              clientMessageId: message.clientMessageId,
              inputText: message.content,
              options: runtimeOptions.options,
              signal: abortController.signal,
            }),
          );
        }
      } else if (!hasTargetThread(target, thread)) {
        throw new Error("This chat no longer exists.");
      } else {
        if (!thread.runtime_session_id) {
          throw new Error("This chat does not have a runtime session.");
        }
        clientMetrics.prepare_refs_wait_on_submit_ms = await prepareAppReferencesForSubmit(
          thread.runtime_session_id,
          message.appReferences,
          abortController.signal,
        );
        response = await submitWithPostMetric(clientMetrics, () =>
          sendRuntimeTurn(
            thread.runtime_session_id,
            message.content,
            message.clientMessageId,
            message.attachments,
            message.appReferences,
            {
              signal: abortController.signal,
              clientMetrics,
              clientSubmissionStartedAt: message.clientSubmissionStartedAt,
            },
          ),
        );
      }
      throwIfAborted(abortController.signal);
      if (!response) {
        throw new Error("Runtime turn was not created.");
      }
      recordSubmitPostMetric(response, clientMetrics);
      if (isPendingIdempotencyResponse(response)) {
        const pending = response.idempotency;
        const pendingSession = response.session;
        const pendingThread =
          response.thread ||
          (!thread && pendingSession
            ? optimisticThreadForPendingSession({
                agentRuntimeConfig,
                draftChat: targetDraftChat,
                messageCreatedAt: new Date().toISOString(),
                session: pendingSession,
                systemPrompt,
              })
            : null);
        const pendingConversationKey = pendingThread ? threadConversationKey(pendingThread.thread_id) : conversationKey;
        if (pendingThread) {
          migrateConversationState(conversationKey, pendingConversationKey);
          delete inFlightSubmissionsRef.current[conversationKey];
          setThreads((current) => upsertOrderedThread(current, pendingThread));
        }
        if (pending?.turn_id) {
          inFlightSubmissionsRef.current[pendingConversationKey] = {
            ...(inFlightSubmissionsRef.current[pendingConversationKey] || {
              abortController,
              clientMessageId: message.clientMessageId,
            }),
            turnId: pending.turn_id,
          };
          setSubmittedTurnForConversation(pendingConversationKey, pending.turn_id);
        }
        if (response.session && isConversationStillActive(conversationKey)) {
          setActiveSession(response.session);
        }
        if (pendingThread && isConversationStillActive(conversationKey)) {
          setActiveThread((current) => (current?.thread_id === pendingThread.thread_id ? { ...current, ...pendingThread } : pendingThread));
          if (!thread) {
            setDraftChat(null);
            notifyActiveThreadChanged(pendingThread.thread_id);
            openChatThreadRouteInShell(pendingThread.thread_id, { navigationScope });
          }
        }
        setConversationSending(conversationKey, false);
        if (pendingConversationKey !== conversationKey) {
          setConversationSending(pendingConversationKey, false);
        }
        return;
      }
      if (!response.turn) {
        throw new Error("Runtime turn was not created.");
      }
      if (!response.session) {
        throw new Error("Runtime session was not returned.");
      }
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
        setEvents((current) => mergeRuntimeEvents(current, response.events || []));
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
        delete inFlightSubmissionsRef.current[threadKey];
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
    const clientSubmissionStartedAt = new Date().toISOString();
    const appReferences = mergeAppReferences(appReferencesFromText(input, composerMentionItems), target.activeAppContext);
    const clientSubmissionMetrics: RuntimeTurnClientMetrics = {};
    const localMessage: QueuedMessage = {
      clientMessageId,
      clientSubmissionStartedAt,
      clientSubmissionMetrics,
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
      let messageAttachments: QueuedMessage["attachments"];
      try {
        if (targetAttachments.length) {
          const readyBeforeSubmit = composerAttachmentsUploadSnapshot(targetAttachments).readyBeforeSubmit;
          const attachmentUploadStartedAt = performance.now();
          messageAttachments = await Promise.all(targetAttachments.map(uploadComposerAttachment));
          recordAttachmentUploadMetrics(
            clientSubmissionMetrics,
            targetAttachments,
            readyBeforeSubmit,
            elapsedMs(attachmentUploadStartedAt),
          );
        } else {
          messageAttachments = [];
        }
      } catch (uploadError) {
        if (isConversationStillActive(resolveConversationKeyAlias(target.conversationKey))) {
          setComposerError(uploadError instanceof Error ? uploadError.message : "Unable to upload attachments.");
          setComposer(input);
          setSelectedReferences(appReferences);
        }
        return;
      }
      const queueConversationKey = resolveConversationKeyAlias(target.conversationKey);
      const queuedMessage = {
        clientMessageId,
        clientSubmissionStartedAt,
        clientSubmissionMetrics: { ...clientSubmissionMetrics },
        content: input,
        attachments: messageAttachments,
        appReferences,
        multiAgentMode,
      };
      const immediateTarget = currentSubmissionTarget(queueConversationKey);
      if (immediateTarget && !isRuntimeBusyRef.current && !sendingByConversationKeyRef.current[queueConversationKey]) {
        const abortController = startSubmission(immediateTarget, queuedMessage);
        void submitMessage(queuedMessage, immediateTarget, abortController);
        return;
      }
      setItemsForConversation(setQueuedMessagesByConversationKey, queueConversationKey, (current) => [
        ...current,
        queuedMessage,
      ]);
      return;
    }
    const abortController = startSubmission(target, localMessage);
    try {
      let uploadedAttachments: QueuedMessage["attachments"] = [];
      if (targetAttachments.length) {
        const readyBeforeSubmit = composerAttachmentsUploadSnapshot(targetAttachments).readyBeforeSubmit;
        const attachmentUploadStartedAt = performance.now();
        uploadedAttachments = await uploadAttachmentsWithAbort(targetAttachments, abortController.signal);
        recordAttachmentUploadMetrics(
          clientSubmissionMetrics,
          targetAttachments,
          readyBeforeSubmit,
          elapsedMs(attachmentUploadStartedAt),
        );
      }
      const message = {
        ...localMessage,
        attachments: uploadedAttachments,
        clientSubmissionMetrics: { ...clientSubmissionMetrics },
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
