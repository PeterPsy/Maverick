import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import type { ChatMessage } from "../api/client";
import type { InterAgentApprovalRecord, InterAgentEventRecord, InterAgentRunDetail } from "../api/client";
import { copyTextToClipboard } from "../lib/clipboard";
import { interAgentBoardLinksByMessageId, visiblePrimaryChatMessages } from "../lib/interAgentTranscript";
import type { MentionItem } from "../lib/mentions";
import { isTerminalRunStatus } from "../lib/interAgentGraph";
import { ChatTranscriptSkeleton } from "./ChatTranscriptSkeleton";
import { InterAgentBoardButton } from "./InterAgentBoardButton";
import { InterAgentRunPanel } from "./InterAgentRunPanel";
import { MessageList } from "./MessageList";
import { MorphingSpinner } from "./ui/morphing-spinner";

const OPENED_INTER_AGENT_BOARD_RUNS_STORAGE_KEY = "chatapp.openedInterAgentBoardRunIds";

export type ChatTranscriptProps = {
  activeInterAgentGraphRunId?: string | null;
  composerOverlayHeight?: number;
  conversationKey?: string;
  error: string | null;
  isLoading: boolean;
  isLoadingOlderHistory?: boolean;
  interAgentApprovalsByRunId?: Record<string, InterAgentApprovalRecord[]>;
  interAgentEventsByRunId?: Record<string, InterAgentEventRecord[]>;
  interAgentRuns?: InterAgentRunDetail[];
  loadingLabel: string;
  mentionItems: MentionItem[];
  messages: ChatMessage[];
  hasMoreOlderMessages?: boolean;
  hasNewerHistory?: boolean;
  isNewerHistoryLoading?: boolean;
  onLoadNewerHistory?: () => void;
  onLoadLatestHistory?: () => void;
  onFollowLatestChange?: (follow: boolean) => void;
  onCloseInterAgentGraph?: () => void;
  onContinueFromProviderOverload?: () => void;
  onLoadOlderMessages?: () => void;
  onOpenInterAgentGraph?: (runId: string) => void;
  onResolveInterAgentApproval?: (approvalId: string, approved: boolean) => Promise<void>;
  speechMaxTextChars?: number;
  speechProviderAvailable?: boolean;
  speechProviderAppId?: string;
  speechProviderQualityProfile?: string;
  speechProviderStreamingSupported?: boolean;
};

export function ChatTranscript({
  activeInterAgentGraphRunId = null,
  composerOverlayHeight = 0,
  conversationKey = "",
  error,
  isLoading,
  isLoadingOlderHistory = false,
  interAgentApprovalsByRunId = {},
  interAgentRuns = [],
  loadingLabel,
  mentionItems,
  messages,
  hasMoreOlderMessages = false,
  hasNewerHistory = false,
  isNewerHistoryLoading = false,
  onLoadNewerHistory,
  onLoadLatestHistory,
  onFollowLatestChange,
  onLoadOlderMessages,
  onContinueFromProviderOverload,
  onOpenInterAgentGraph = () => undefined,
  onResolveInterAgentApproval = async () => undefined,
  speechMaxTextChars = 0,
  speechProviderAvailable = true,
  speechProviderAppId = "",
  speechProviderQualityProfile = "",
  speechProviderStreamingSupported = false,
}: ChatTranscriptProps) {
  const viewportRef = useRef<HTMLDivElement | null>(null);
  const scrollAnchorRef = useRef<{ height: number; top: number; row?: string; offset?: number } | null>(null);
  const loadOlderPendingRef = useRef(false);
  const [isNearBottom, setIsNearBottom] = useState(true);
  const [isAtBottom, setIsAtBottom] = useState(true);
  const [showScrollJump, setShowScrollJump] = useState(false);
  const [expandedMessages, setExpandedMessages] = useState<Set<string>>(new Set());
  const [speakingMessageId, setSpeakingMessageId] = useState<string | null>(null);
  const [openedInterAgentBoardRunIds, setOpenedInterAgentBoardRunIds] = useState<Set<string>>(
    () => readOpenedInterAgentBoardRunIds(),
  );

  function scrollToBottom() {
    onFollowLatestChange?.(true);
    setIsNearBottom(true);
    if (hasNewerHistory) {
      onLoadLatestHistory?.();
      return;
    }
    const viewport = viewportRef.current;
    if (!viewport) {
      return;
    }
    viewport.scrollTo({ top: viewport.scrollHeight, behavior: "smooth" });
    setShowScrollJump(false);
  }

  const toggleExpanded = useCallback((messageId: string) => {
    setExpandedMessages((current) => {
      const next = new Set(current);
      if (next.has(messageId)) {
        next.delete(messageId);
      } else {
        next.add(messageId);
      }
      return next;
    });
  }, []);

  const copyMessage = useCallback((content: string) => {
    return copyTextToClipboard(content);
  }, []);

  const markInterAgentBoardOpened = useCallback((runId: string) => {
    const normalizedRunId = runId.trim();
    if (!normalizedRunId) {
      return;
    }
    setOpenedInterAgentBoardRunIds((current) => {
      if (current.has(normalizedRunId)) {
        return current;
      }
      const next = new Set(current);
      next.add(normalizedRunId);
      writeOpenedInterAgentBoardRunIds(next);
      return next;
    });
  }, []);

  const openInterAgentGraph = useCallback((runId: string) => {
    markInterAgentBoardOpened(runId);
    onOpenInterAgentGraph(runId);
  }, [markInterAgentBoardOpened, onOpenInterAgentGraph]);

  function updateScrollState() {
    const viewport = viewportRef.current;
    if (!viewport) {
      return;
    }
    if (viewport.scrollTop < 80 && hasMoreOlderMessages && !isLoadingOlderHistory && !loadOlderPendingRef.current) {
      loadOlderPendingRef.current = true;
      const top = viewport.getBoundingClientRect().top;
      const row = [...viewport.querySelectorAll<HTMLElement>('[data-transcript-row]')]
        .find(element => !element.hidden && element.getBoundingClientRect().bottom > top);
      scrollAnchorRef.current = { height: viewport.scrollHeight, top: viewport.scrollTop,
        row: row?.dataset.transcriptRow, offset: row ? row.getBoundingClientRect().top - top : undefined };
      onLoadOlderMessages?.();
    }
    const distanceFromBottom = viewport.scrollHeight - viewport.scrollTop - viewport.clientHeight;
    setIsAtBottom(distanceFromBottom < 1);
    const nextIsNearBottom = distanceFromBottom < 96;
    setIsNearBottom(nextIsNearBottom);
    onFollowLatestChange?.(nextIsNearBottom && !hasNewerHistory);
    if (nextIsNearBottom) {
      setShowScrollJump(false);
    }
  }

  useEffect(() => {
    const viewport = viewportRef.current;
    if (!viewport) {
      return;
    }
    if (isNearBottom) {
      viewport.scrollTop = viewport.scrollHeight;
      setShowScrollJump(false);
    } else {
      setShowScrollJump(true);
    }
  }, [messages.length, isLoading, error]);

  useLayoutEffect(() => {
    const viewport = viewportRef.current;
    scrollAnchorRef.current = null;
    loadOlderPendingRef.current = false;
    setIsNearBottom(true);
    setIsAtBottom(true);
    onFollowLatestChange?.(true);
    setShowScrollJump(false);
    setExpandedMessages(new Set());
    setSpeakingMessageId(null);
    if (viewport) {
      viewport.scrollTop = viewport.scrollHeight;
    }
  }, [conversationKey]);

  useLayoutEffect(() => {
    const viewport = viewportRef.current;
    const anchor = scrollAnchorRef.current;
    if (!viewport || !anchor || isLoadingOlderHistory) {
      return;
    }
    // The data window may also drop rows below the viewport while prepending.
    // Preserve the visible row itself instead of using total height alone.
    const row = anchor.row ? [...viewport.querySelectorAll<HTMLElement>('[data-transcript-row]')]
      .find(element => element.dataset.transcriptRow === anchor.row) : null;
    viewport.scrollTop = row && anchor.offset !== undefined
      ? viewport.scrollTop + row.getBoundingClientRect().top - viewport.getBoundingClientRect().top - anchor.offset
      : viewport.scrollHeight - anchor.height + anchor.top;
    scrollAnchorRef.current = null;
    loadOlderPendingRef.current = false;
  }, [messages.length, isLoadingOlderHistory]);

  useLayoutEffect(() => {
    const viewport = viewportRef.current;
    if (!viewport || !isNearBottom) {
      return;
    }
    viewport.scrollTop = viewport.scrollHeight;
    setShowScrollJump(false);
  }, [composerOverlayHeight, isNearBottom, messages]);

  const latestToolMessageId =
    [...messages]
      .reverse()
      .find((message) => message.role === "tool" && (message.toolCalls?.length || message.toolCall))?.id || null;
  const liveInterAgentRun = useMemo(
    () => [...interAgentRuns].reverse().find((detail) => !isTerminalRunStatus(detail.run.status)) || null,
    [interAgentRuns],
  );
  const primaryMessages = useMemo(() => visiblePrimaryChatMessages(messages), [messages]);
  const boardLinksByMessageId = useMemo(
    () =>
      interAgentBoardLinksByMessageId({
        messages,
        openedRunIds: openedInterAgentBoardRunIds,
        runs: interAgentRuns,
      }),
    [interAgentRuns, messages, openedInterAgentBoardRunIds],
  );

  const hasInterAgentContent =
    interAgentRuns.length > 0 || Boolean(activeInterAgentGraphRunId) || Object.values(interAgentApprovalsByRunId).some((items) => items.length > 0);

  if (!primaryMessages.length && !hasInterAgentContent && isLoading && !error) {
    return (
      <section className="chatapp-chat-scroll" aria-busy="true" aria-live="polite">
        <div className="chatapp-chat-scroll__inner chatapp-chat-scroll__inner--skeleton" onScroll={updateScrollState} ref={viewportRef}>
          <ChatTranscriptSkeleton label={loadingLabel || "Loading history"} />
        </div>
      </section>
    );
  }

  if (!primaryMessages.length && !hasInterAgentContent && !isLoading && !error) {
    return (
      <section className="chatapp-chat-scroll">
        <div className="chatapp-chat-scroll__inner" onScroll={updateScrollState} ref={viewportRef} />
      </section>
    );
  }

  return (
    <section className={`chatapp-chat-scroll${isAtBottom ? ' is-at-bottom' : ''}`} aria-live="polite">
      <div className="chatapp-chat-scroll__inner" onScroll={updateScrollState} ref={viewportRef}>
        {isLoadingOlderHistory ? (
          <div className="chatapp-history-loader" role="status" aria-live="polite">
            <MorphingSpinner size="sm" className="chatapp-history-loader__icon" />
            <span>Loading earlier messages</span>
          </div>
        ) : null}
        <InterAgentRunPanel
          approvalsByRunId={interAgentApprovalsByRunId}
          onResolveApproval={onResolveInterAgentApproval}
          runs={interAgentRuns}
        />
        <MessageList
          viewportRef={viewportRef}
          expandedMessages={expandedMessages}
          interAgentBoardLinksByMessageId={boardLinksByMessageId}
          latestToolMessageId={latestToolMessageId}
          mentionItems={mentionItems}
          messages={primaryMessages}
          onActiveSpeechMessageChange={setSpeakingMessageId}
          onCopyMessage={copyMessage}
          onContinueFromProviderOverload={onContinueFromProviderOverload}
          onOpenInterAgentGraph={openInterAgentGraph}
          onToggleExpanded={toggleExpanded}
          speakingMessageId={speakingMessageId}
          speechMaxTextChars={speechMaxTextChars}
          speechProviderAppId={speechProviderAppId}
          speechProviderAvailable={speechProviderAvailable}
          speechProviderQualityProfile={speechProviderQualityProfile}
          speechProviderStreamingSupported={speechProviderStreamingSupported}
        />
        {hasNewerHistory ? (
          <div className="chatapp-history-loader">
            <button type="button" disabled={isNewerHistoryLoading} onClick={onLoadNewerHistory}>
              {isNewerHistoryLoading ? 'Loading newer messages' : 'Load newer messages'}
            </button>
          </div>
        ) : null}
        {isLoading ? (
          <article className="chatapp-bubble is-agent">
            <div className="chatapp-pending-turn" aria-live="polite">
              <MorphingSpinner size="sm" className="chatapp-pending-turn__icon" />
              <span className="chatapp-pending-turn__label">{loadingLabel}</span>
              {liveInterAgentRun ? (
                <InterAgentBoardButton
                  className="chatapp-pending-turn__board"
                  onOpen={openInterAgentGraph}
                  runId={liveInterAgentRun.run.run_id}
                  state="live"
                />
              ) : null}
            </div>
          </article>
        ) : null}
        {error ? (
          <div className="chatapp-error" role="alert">
            <span className="chatapp-error__icon material-symbols-rounded" aria-hidden="true">
              error
            </span>
            <span className="chatapp-error__label">{error}</span>
          </div>
        ) : null}
      </div>
      {showScrollJump || hasNewerHistory ? (
        <button className="chatapp-chat-scroll-jump" disabled={isNewerHistoryLoading} onClick={scrollToBottom} type="button" aria-label="Jump to latest message">
          <span aria-hidden="true" className="material-symbols-rounded">
            arrow_downward
          </span>
        </button>
      ) : null}
    </section>
  );
}

function readOpenedInterAgentBoardRunIds(): Set<string> {
  if (typeof window === "undefined") {
    return new Set();
  }
  try {
    const raw = window.localStorage.getItem(OPENED_INTER_AGENT_BOARD_RUNS_STORAGE_KEY);
    const parsed = raw ? JSON.parse(raw) : [];
    return new Set(Array.isArray(parsed) ? parsed.filter((item): item is string => typeof item === "string" && Boolean(item.trim())) : []);
  } catch {
    return new Set();
  }
}

function writeOpenedInterAgentBoardRunIds(runIds: ReadonlySet<string>) {
  if (typeof window === "undefined") {
    return;
  }
  try {
    window.localStorage.setItem(OPENED_INTER_AGENT_BOARD_RUNS_STORAGE_KEY, JSON.stringify([...runIds].slice(-200)));
  } catch {
    // Best-effort UI receipt only.
  }
}
