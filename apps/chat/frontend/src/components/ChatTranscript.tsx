import { useEffect, useLayoutEffect, useRef, useState } from "react";
import type { ChatMessage } from "../api/client";
import type { InterAgentApprovalRecord, InterAgentEventRecord, InterAgentRunDetail } from "../api/client";
import type { MentionItem } from "../lib/mentions";
import { ChatTranscriptSkeleton } from "./ChatTranscriptSkeleton";
import { InterAgentRunPanel } from "./InterAgentRunPanel";
import { MessageList } from "./MessageList";
import { MorphingSpinner } from "./ui/morphing-spinner";

export type ChatTranscriptProps = {
  activeInterAgentGraphRunId?: string | null;
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
  onCloseInterAgentGraph?: () => void;
  onLoadOlderMessages?: () => void;
  onOpenInterAgentGraph?: (runId: string) => void;
  onResolveInterAgentApproval?: (approvalId: string, approved: boolean) => Promise<void>;
  speechMaxTextChars?: number;
  speechProviderAvailable?: boolean;
  speechProviderAppId?: string;
  speechProviderQualityProfile?: string;
};

export function ChatTranscript({
  activeInterAgentGraphRunId = null,
  error,
  isLoading,
  isLoadingOlderHistory = false,
  interAgentApprovalsByRunId = {},
  interAgentEventsByRunId = {},
  interAgentRuns = [],
  loadingLabel,
  mentionItems,
  messages,
  hasMoreOlderMessages = false,
  onCloseInterAgentGraph = () => undefined,
  onLoadOlderMessages,
  onOpenInterAgentGraph = () => undefined,
  onResolveInterAgentApproval = async () => undefined,
  speechMaxTextChars = 0,
  speechProviderAvailable = true,
  speechProviderAppId = "",
  speechProviderQualityProfile = "",
}: ChatTranscriptProps) {
  const viewportRef = useRef<HTMLDivElement | null>(null);
  const scrollAnchorRef = useRef<{ height: number; top: number } | null>(null);
  const loadOlderPendingRef = useRef(false);
  const [isNearBottom, setIsNearBottom] = useState(true);
  const [showScrollJump, setShowScrollJump] = useState(false);
  const [expandedMessages, setExpandedMessages] = useState<Set<string>>(new Set());
  const [speakingMessageId, setSpeakingMessageId] = useState<string | null>(null);

  function scrollToBottom() {
    const viewport = viewportRef.current;
    if (!viewport) {
      return;
    }
    viewport.scrollTo({ top: viewport.scrollHeight, behavior: "smooth" });
    setShowScrollJump(false);
  }

  function toggleExpanded(messageId: string) {
    setExpandedMessages((current) => {
      const next = new Set(current);
      if (next.has(messageId)) {
        next.delete(messageId);
      } else {
        next.add(messageId);
      }
      return next;
    });
  }

  async function copyMessage(content: string) {
    if (!content || !navigator.clipboard) {
      return;
    }
    await navigator.clipboard.writeText(content);
  }

  function updateScrollState() {
    const viewport = viewportRef.current;
    if (!viewport) {
      return;
    }
    if (viewport.scrollTop < 80 && hasMoreOlderMessages && !isLoadingOlderHistory && !loadOlderPendingRef.current) {
      loadOlderPendingRef.current = true;
      scrollAnchorRef.current = { height: viewport.scrollHeight, top: viewport.scrollTop };
      onLoadOlderMessages?.();
    }
    const distanceFromBottom = viewport.scrollHeight - viewport.scrollTop - viewport.clientHeight;
    const nextIsNearBottom = distanceFromBottom < 96;
    setIsNearBottom(nextIsNearBottom);
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
    const anchor = scrollAnchorRef.current;
    if (!viewport || !anchor) {
      return;
    }
    viewport.scrollTop = viewport.scrollHeight - anchor.height + anchor.top;
    scrollAnchorRef.current = null;
    loadOlderPendingRef.current = false;
  }, [messages.length, isLoadingOlderHistory]);

  const latestToolMessageId =
    [...messages]
      .reverse()
      .find((message) => message.role === "tool" && (message.toolCalls?.length || message.toolCall))?.id || null;

  const activeGraphRun = activeInterAgentGraphRunId
    ? interAgentRuns.find((detail) => detail.run.run_id === activeInterAgentGraphRunId) || null
    : null;
  const hasInterAgentContent =
    interAgentRuns.length > 0 || Boolean(activeInterAgentGraphRunId) || Object.values(interAgentApprovalsByRunId).some((items) => items.length > 0);

  if (!messages.length && !hasInterAgentContent && isLoading && !error) {
    return (
      <section className="chatapp-chat-scroll" aria-busy="true" aria-live="polite">
        <div className="chatapp-chat-scroll__inner chatapp-chat-scroll__inner--skeleton" onScroll={updateScrollState} ref={viewportRef}>
          <ChatTranscriptSkeleton label={loadingLabel || "Loading history"} />
        </div>
      </section>
    );
  }

  if (!messages.length && !hasInterAgentContent && !isLoading && !error) {
    return (
      <section className="chatapp-chat-scroll">
        <div className="chatapp-chat-scroll__inner" onScroll={updateScrollState} ref={viewportRef} />
      </section>
    );
  }

  return (
    <section className="chatapp-chat-scroll" aria-live="polite">
      <div className="chatapp-chat-scroll__inner" onScroll={updateScrollState} ref={viewportRef}>
        {isLoadingOlderHistory ? (
          <div className="chatapp-history-loader" role="status" aria-live="polite">
            <MorphingSpinner size="sm" className="chatapp-history-loader__icon" />
            <span>Loading earlier messages</span>
          </div>
        ) : null}
        {activeInterAgentGraphRunId ? (
          <InterAgentGraphView
            approvals={interAgentApprovalsByRunId[activeInterAgentGraphRunId] || []}
            events={interAgentEventsByRunId[activeInterAgentGraphRunId] || []}
            onClose={onCloseInterAgentGraph}
            runDetail={activeGraphRun}
            runId={activeInterAgentGraphRunId}
          />
        ) : null}
        <InterAgentRunPanel
          approvalsByRunId={interAgentApprovalsByRunId}
          eventsByRunId={interAgentEventsByRunId}
          onOpenGraph={onOpenInterAgentGraph}
          onResolveApproval={onResolveInterAgentApproval}
          runs={interAgentRuns}
        />
        <MessageList
          expandedMessages={expandedMessages}
          latestToolMessageId={latestToolMessageId}
          mentionItems={mentionItems}
          messages={messages}
          onActiveSpeechMessageChange={setSpeakingMessageId}
          onCopyMessage={copyMessage}
          onOpenInterAgentGraph={onOpenInterAgentGraph}
          onToggleExpanded={toggleExpanded}
          speakingMessageId={speakingMessageId}
          speechMaxTextChars={speechMaxTextChars}
          speechProviderAppId={speechProviderAppId}
          speechProviderAvailable={speechProviderAvailable}
          speechProviderQualityProfile={speechProviderQualityProfile}
        />
        {isLoading ? (
          <article className="chatapp-bubble is-agent">
            <div className="chatapp-pending-turn" aria-live="polite">
              <MorphingSpinner size="sm" className="chatapp-pending-turn__icon" />
              <span className="chatapp-pending-turn__label">{loadingLabel}</span>
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
      {showScrollJump ? (
        <button className="chatapp-chat-scroll-jump" onClick={scrollToBottom} type="button" aria-label="Jump to latest message">
          <span aria-hidden="true" className="material-symbols-rounded">
            arrow_downward
          </span>
        </button>
      ) : null}
    </section>
  );
}

function InterAgentGraphView({
  approvals,
  events,
  onClose,
  runDetail,
  runId,
}: {
  approvals: InterAgentApprovalRecord[];
  events: InterAgentEventRecord[];
  onClose: () => void;
  runDetail: InterAgentRunDetail | null;
  runId: string;
}) {
  const pendingApprovalCount = approvals.filter((approval) => approval.status === "pending").length;
  return (
    <section className="chatapp-inter-agent-graph" aria-label="Inter-agent graph">
      <header className="chatapp-inter-agent-graph__header">
        <div>
          <span className="chatapp-inter-agent-graph__eyebrow">Graph</span>
          <h2>{runDetail ? runStatusLabel(runDetail.run.status) : "Loading run"}</h2>
        </div>
        <button className="chatapp-inter-agent-graph__close" onClick={onClose} type="button" aria-label="Close graph">
          <span className="material-symbols-rounded" aria-hidden="true">
            close
          </span>
        </button>
      </header>
      <div className="chatapp-inter-agent-graph__body">
        <div className="chatapp-inter-agent-graph__participants">
          {(runDetail?.participants || []).map((participant) => (
            <div className={`chatapp-inter-agent-graph__node is-${participant.status}`} key={participant.participant_id}>
              <span className="material-symbols-rounded" aria-hidden="true">
                {participant.kind === "orchestrator" ? "hub" : "smart_toy"}
              </span>
              <div>
                <strong>{participant.label}</strong>
                <span>{participant.status}</span>
              </div>
            </div>
          ))}
          {!runDetail ? <div className="chatapp-inter-agent-graph__empty">Run {runId} is loading.</div> : null}
        </div>
        <ol className="chatapp-inter-agent-graph__timeline">
          {events.slice(-8).map((event) => (
            <li key={event.event_id}>
              <span>{event.event_type.replace(/^inter_agent\./, "").replace(/\./g, " ")}</span>
              <strong>{textPayload(event.payload.summary) || textPayload(event.payload.status) || event.visibility_plane}</strong>
            </li>
          ))}
          {!events.length ? <li>No summary events yet.</li> : null}
        </ol>
      </div>
      {pendingApprovalCount ? <div className="chatapp-inter-agent-graph__approval">{pendingApprovalCount} approval pending</div> : null}
    </section>
  );
}

function runStatusLabel(status: string): string {
  if (status === "waiting_approval") {
    return "Waiting approval";
  }
  return status
    .split("_")
    .map((part) => part.slice(0, 1).toUpperCase() + part.slice(1))
    .join(" ");
}

function textPayload(value: unknown): string {
  return typeof value === "string" ? value.trim() : "";
}
