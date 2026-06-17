import { Dispatch, SetStateAction, useEffect, useState } from "react";
import {
  AppReference,
  ChatThread,
  InterAgentRunDetail,
  MultiAgentComposerMode,
  RuntimeEvent,
  RuntimeSession,
  RuntimeTurn,
  createInterAgentRun,
  createRuntimeSession,
  createRuntimeSessionWithTurn,
  executeInterAgentRun,
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
  skill_catalog_app_id: string;
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
      if (message.multiAgentMode && message.multiAgentMode !== "off") {
        await submitInterAgentMessage(message);
        return;
      }
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
            skill_catalog_app_id: agentRuntimeConfig?.skill_catalog_app_id,
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

  async function submitInterAgentMessage(message: QueuedMessage) {
    let thread = activeThread;
    let session: RuntimeSession | null = null;
    const agentRuntimeConfig = await selectedAgentRuntimeConfig(activeAppContext);
    if (!thread) {
      const systemPrompt = agentRuntimeConfig?.system_prompt || draftChat?.systemPrompt || (await loadDefaultSystemPrompt(activeAppContext));
      session = await createRuntimeSession({
        agent_id: agentRuntimeConfig?.agent_id,
        agent_role_id: agentRuntimeConfig?.agent_role_id,
        agent_type_id: agentRuntimeConfig?.agent_type_id,
        project_id: draftChat?.projectId ?? null,
        source_app_id: agentRuntimeConfig?.source_app_id || "chat",
        system_prompt: systemPrompt,
        skill_catalog_app_id: agentRuntimeConfig?.skill_catalog_app_id,
        skill_ids: agentRuntimeConfig?.skill_ids || [],
        title: "New chat",
      });
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
        project_id: draftChat?.projectId ?? null,
        archived: false,
        availability: "queued",
        created_at: now,
        updated_at: now,
        last_user_message_at: now,
      };
      setDraftChat(null);
    } else if (!threads.some((item) => item.thread_id === thread?.thread_id)) {
      throw new Error("This chat no longer exists.");
    }
    if (!thread.runtime_session_id) {
      throw new Error("This chat does not have a runtime session.");
    }

    const runDetail = await createInterAgentRun(
      interAgentRunPayload({
        agentRuntimeConfig,
        mode: message.multiAgentMode || "auto",
        thread,
        clientMessageId: message.clientMessageId,
      }),
    );
    onInterAgentRunChanged?.(runDetail);
    const executed = await executeInterAgentRun(runDetail.run.run_id, {
      input_text: message.content,
      client_message_id: message.clientMessageId,
      attachments: message.attachments,
      app_references: message.appReferences,
      async: true,
    });
    onInterAgentRunChanged?.(executed);
    if (session) {
      setActiveSession(session);
    }
    if (executed.root_runtime_turn) {
      setActiveTurn(executed.root_runtime_turn);
    }
    if (executed.root_runtime_events?.length) {
      setEvents((current) => mergeRuntimeEvents(current, executed.root_runtime_events || []));
    }
    const userMessageAt = executed.root_runtime_turn?.created_at || new Date().toISOString();
    const availability =
      executed.root_runtime_turn?.status === "queued" || executed.root_runtime_turn?.status === "active" ? executed.root_runtime_turn.status : "free";
    const optimisticThread = {
      ...thread,
      availability,
      last_user_message_at: userMessageAt,
      updated_at: userMessageAt,
    };
    setActiveThread((current) => (current?.thread_id === optimisticThread.thread_id ? { ...current, ...optimisticThread } : optimisticThread));
    setThreads((current) => upsertOrderedThread(current, optimisticThread));
    if (!activeThread) {
      notifyActiveThreadChanged(optimisticThread.thread_id);
      openChatThreadRouteInShell(optimisticThread.thread_id, { navigationScope });
    }
    if (!executed.root_runtime_turn || (executed.root_runtime_turn.status !== "queued" && executed.root_runtime_turn.status !== "active")) {
      setPendingUserMessages((current) => current.filter((item) => item.clientMessageId !== message.clientMessageId));
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
      setQueuedMessages((current) => [...current, { clientMessageId, content: input, attachments: messageAttachments, appReferences, multiAgentMode }]);
      return;
    }
    await submitMessage({ clientMessageId, content: input, attachments: messageAttachments, appReferences, multiAgentMode });
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
  const participantLabel = agentRuntimeConfig?.title || thread.agent_label || "Maverick agent";
  const agentTypeId = agentRuntimeConfig?.agent_type_id || thread.agent_type_id || "";
  const agentSnapshot =
    agentRuntimeConfig?.agent_type_id
      ? {
          agent_type_id: agentRuntimeConfig.agent_type_id,
          label: participantLabel,
          system_prompt: agentRuntimeConfig.system_prompt || "",
          skill_ids: agentRuntimeConfig.skill_ids || [],
          skill_catalog_app_id: agentRuntimeConfig.skill_catalog_app_id || "skills",
        }
      : undefined;
  const participant = {
    participant_id: "assistant",
    kind: "agent" as const,
    execution_mode: "child_runtime_session" as const,
    label: participantLabel,
    ...(agentTypeId ? { agent_type_id: agentTypeId } : {}),
    ...(agentSnapshot ? { agent_snapshot: agentSnapshot } : {}),
  };
  return {
    thread_id: thread.thread_id,
    root_runtime_session_id: thread.runtime_session_id,
    mode: "manager_tools" as const,
    idempotency_key: `chat:${clientMessageId}:${mode}`,
    participants: [
      {
        participant_id: "orchestrator",
        kind: "orchestrator" as const,
        execution_mode: "root_orchestrator" as const,
        label: "Orchestrator",
      },
      participant,
    ],
    budget: {
      max_participants: 2,
      max_concurrent_participants: mode === "multi" ? 2 : 1,
      max_total_turns: mode === "multi" ? 4 : 2,
      max_turns_per_participant: mode === "multi" ? 2 : 1,
      max_tool_calls: mode === "multi" ? 4 : 1,
    },
  };
}
