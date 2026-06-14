import { Dispatch, SetStateAction, useEffect, useState } from "react";
import {
  AppReference,
  ChatThread,
  RuntimeEvent,
  RuntimeSession,
  RuntimeTurn,
  createRuntimeSessionWithTurn,
  sendRuntimeTurn,
} from "../api/client";
import type { ComposerAttachment } from "../lib/attachments";
import { hasInvalidAttachments } from "../lib/attachments";
import { ActiveAppContext, mergeAppReferences } from "../lib/activeAppContext";
import { appReferencesFromText } from "../lib/mentions";
import type { MentionItem } from "../lib/mentions";
import { PendingMessage, QueuedMessage, uploadComposerAttachment } from "../lib/messageState";
import { mergeRuntimeEvents } from "../lib/runtimeEvents";
import { loadDefaultSystemPrompt } from "../lib/activeAppContext";
import { openChatThreadRouteInShell } from "../lib/shellNavigation";
import { upsertOrderedThread } from "../lib/threadNavigation";

export type DraftChat = {
  projectId: string | null;
  systemPrompt: string;
};

export type AgentRuntimeConfig = {
  agent_id: string;
  agent_role_id: string;
  agent_type_id: string;
  skill_ids: string[];
  source_app_id: string;
  system_prompt: string;
  title: string;
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
  navigationScope: string;
  notifyActiveThreadChanged: (activeThreadId: string) => void;
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
  navigationScope,
  notifyActiveThreadChanged,
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
  const [pendingUserMessages, setPendingUserMessages] = useState<PendingMessage[]>([]);
  const [failedUserMessages, setFailedUserMessages] = useState<PendingMessage[]>([]);
  const [queuedMessages, setQueuedMessages] = useState<QueuedMessage[]>([]);
  const [isSending, setIsSending] = useState(false);

  async function submitMessage(message: QueuedMessage) {
    setPendingUserMessages((current) => [
      ...current,
      {
        clientMessageId: message.clientMessageId,
        content: message.content,
        createdAt: new Date().toISOString(),
        attachments: message.attachments,
        appReferences: message.appReferences,
      },
    ]);
    setFailedUserMessages((current) => current.filter((item) => item.clientMessageId !== message.clientMessageId));
    setIsSending(true);
    setError(null);
    try {
      let thread = activeThread;
      let response: Awaited<ReturnType<typeof sendRuntimeTurn>>;
      if (!thread) {
        const agentRuntimeConfig = await selectedAgentRuntimeConfig(activeAppContext);
        const systemPrompt = agentRuntimeConfig?.system_prompt || draftChat?.systemPrompt || (await loadDefaultSystemPrompt(activeAppContext));
        response = await createRuntimeSessionWithTurn({
          appReferences: message.appReferences,
          attachments: message.attachments,
          clientMessageId: message.clientMessageId,
          inputText: message.content,
          options: {
            agent_id: agentRuntimeConfig?.agent_id,
            agent_role_id: agentRuntimeConfig?.agent_role_id,
            agent_type_id: agentRuntimeConfig?.agent_type_id,
            project_id: draftChat?.projectId ?? null,
            source_app_id: agentRuntimeConfig?.source_app_id || "chat",
            system_prompt: systemPrompt,
            skill_ids: agentRuntimeConfig?.skill_ids || [],
            title: "New chat",
          },
        });
        setDraftChat(null);
      } else if (!threads.some((item) => item.thread_id === thread?.thread_id)) {
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
        );
      }
      const responseThread = response.thread;
      const baseThread = responseThread || thread;
      if (!baseThread) {
        throw new Error("Runtime thread was not created.");
      }
      setActiveSession(response.session);
      setActiveTurn(response.turn);
      setEvents((current) => mergeRuntimeEvents(current, response.events));
      const userMessageAt = response.turn.created_at || new Date().toISOString();
      const optimisticThread = {
        ...baseThread,
        ...(responseThread || {}),
        availability: response.turn.status === "queued" || response.turn.status === "active" ? response.turn.status : "free",
        last_user_message_at: userMessageAt,
      };
      setActiveThread((current) => (current?.thread_id === optimisticThread.thread_id ? { ...current, ...optimisticThread } : optimisticThread));
      setThreads((current) => upsertOrderedThread(current, optimisticThread));
      if (!thread) {
        notifyActiveThreadChanged(optimisticThread.thread_id);
        openChatThreadRouteInShell(optimisticThread.thread_id, { navigationScope });
      }
      if (response.turn.status !== "queued" && response.turn.status !== "active") {
        setPendingUserMessages((current) => current.filter((item) => item.clientMessageId !== message.clientMessageId));
      }
    } catch (sendError) {
      setError(sendError instanceof Error ? sendError.message : "Unable to send message.");
      setActiveTurn(null);
      setComposer(message.content);
      setSelectedReferences(message.appReferences);
      setPendingUserMessages((current) => current.filter((item) => item.clientMessageId !== message.clientMessageId));
      setFailedUserMessages((current) => [
        ...current,
        {
          clientMessageId: message.clientMessageId,
          content: message.content,
          createdAt: new Date().toISOString(),
          attachments: message.attachments,
          appReferences: message.appReferences,
        },
      ]);
    } finally {
      setIsSending(false);
    }
  }

  async function handleSend() {
    const input = composer.trim();
    if ((!input && !attachments.length) || hasInvalidAttachments(attachments)) {
      return;
    }
    const clientMessageId = crypto.randomUUID();
    setComposerError(null);
    let messageAttachments;
    try {
      messageAttachments = await Promise.all(attachments.map(uploadComposerAttachment));
    } catch (uploadError) {
      setComposerError(uploadError instanceof Error ? uploadError.message : "Unable to upload attachments.");
      return;
    }
    setComposer("");
    setSelectedReferences([]);
    clearAttachments();
    const appReferences = mergeAppReferences(appReferencesFromText(input, composerMentionItems), activeAppContext);
    if (isRuntimeBusy || isSending) {
      setQueuedMessages((current) => [...current, { clientMessageId, content: input, attachments: messageAttachments, appReferences }]);
      return;
    }
    await submitMessage({ clientMessageId, content: input, attachments: messageAttachments, appReferences });
  }

  useEffect(() => {
    if (isBootstrapping || isHistoryLoading || isRuntimeBusy || isSending || queuedMessages.length === 0) {
      return;
    }
    const [nextMessage, ...remainingMessages] = queuedMessages;
    setQueuedMessages(remainingMessages);
    void submitMessage(nextMessage);
  }, [isBootstrapping, isHistoryLoading, isRuntimeBusy, isSending, queuedMessages]);

  return {
    failedUserMessages,
    handleSend,
    isSending,
    pendingUserMessages,
    queuedMessages,
    setFailedUserMessages,
    setPendingUserMessages,
    setQueuedMessages,
  };
}
