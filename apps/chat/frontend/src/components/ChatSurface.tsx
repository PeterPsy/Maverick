import type { CSSProperties, RefObject } from "react";
import { ChatComposer } from "./ChatComposer";
import type { ChatComposerProps } from "./ChatComposer";
import { ChatTranscript } from "./ChatTranscript";
import type { ChatTranscriptProps } from "./ChatTranscript";
import { InterAgentGraphView } from "./InterAgentGraphView";

type ChatSurfaceState = {
  chatMainStyle?: CSSProperties;
  isEmptyChatView: boolean;
};

type ChatSurfaceActions = {
  dockedComposerRef: RefObject<HTMLDivElement | null>;
};

export type ChatSurfaceProps = {
  composerProps: ChatComposerProps;
  surfaceActions: ChatSurfaceActions;
  surfaceState: ChatSurfaceState;
  transcriptProps: ChatTranscriptProps;
};

export function ChatSurface({ composerProps, surfaceActions, surfaceState, transcriptProps }: ChatSurfaceProps) {
  const { chatMainStyle, isEmptyChatView } = surfaceState;
  const { dockedComposerRef } = surfaceActions;
  const activeInterAgentGraphRunId = transcriptProps.activeInterAgentGraphRunId || null;
  const activeGraphRun = activeInterAgentGraphRunId
    ? transcriptProps.interAgentRuns?.find((detail) => detail.run.run_id === activeInterAgentGraphRunId) || null
    : null;
  const isAgentNodesView = Boolean(activeInterAgentGraphRunId);

  return (
    <section className="chatapp-chat-panel">
      <div className={`chatapp-chat-workspace ${isEmptyChatView ? "is-empty-chat" : ""} ${isAgentNodesView ? "is-agent-nodes-view" : ""}`}>
        <div
          className={`chatapp-chat-main ${isEmptyChatView ? "is-empty-chat" : ""} ${isAgentNodesView ? "is-agent-nodes-view" : ""}`}
          style={isAgentNodesView ? undefined : chatMainStyle}
        >
          {isAgentNodesView && activeInterAgentGraphRunId ? (
            <InterAgentGraphView
              initialApprovals={transcriptProps.interAgentApprovalsByRunId?.[activeInterAgentGraphRunId] || []}
              initialEvents={transcriptProps.interAgentEventsByRunId?.[activeInterAgentGraphRunId] || []}
              initialRunDetail={activeGraphRun}
              onClose={transcriptProps.onCloseInterAgentGraph || (() => undefined)}
              runId={activeInterAgentGraphRunId}
            />
          ) : isEmptyChatView ? (
            <div className="chatapp-empty-chat-stage">
              <div className="chatapp-empty-chat-stage__copy">
                <h1>How can I help today?</h1>
                <span aria-hidden="true" />
                <p>Type a command or ask Maverick a question</p>
              </div>
              <ChatComposer {...composerProps} isEmptyMode />
            </div>
          ) : (
            <ChatTranscript {...transcriptProps} />
          )}
          {!isEmptyChatView && !isAgentNodesView ? (
            <div className="chatapp-composer-dock" ref={dockedComposerRef}>
              <ChatComposer {...composerProps} />
            </div>
          ) : null}
        </div>
      </div>
    </section>
  );
}
