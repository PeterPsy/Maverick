import { useEffect, useMemo, useState, type CSSProperties } from "react";
import {
  getInterAgentParticipantTranscript,
  type InterAgentApprovalRecord,
  type InterAgentEventRecord,
  type InterAgentParticipantTranscriptPayload,
  type InterAgentRunDetail,
  type InterAgentVisibilityPlane,
} from "../api/client";
import { useInterAgentGraph } from "../hooks/useInterAgentGraph";
import { eventSummary, isTerminalRunStatus, participantIcon, runStatusLabel } from "../lib/interAgentGraph";

type InterAgentGraphViewProps = {
  initialApprovals?: InterAgentApprovalRecord[];
  initialEvents?: InterAgentEventRecord[];
  initialRunDetail?: InterAgentRunDetail | null;
  onClose: () => void;
  runId: string;
};

const GRAPH_VISIBILITY_PLANE: InterAgentVisibilityPlane = "detail";
const TRANSCRIPT_LIMIT = 80;

export function InterAgentGraphView({
  initialApprovals = [],
  initialEvents = [],
  initialRunDetail = null,
  onClose,
  runId,
}: InterAgentGraphViewProps) {
  const [selectedParticipantId, setSelectedParticipantId] = useState<string | null>(null);
  const [transcript, setTranscript] = useState<InterAgentParticipantTranscriptPayload | null>(null);
  const [transcriptError, setTranscriptError] = useState<string | null>(null);
  const [transcriptLoading, setTranscriptLoading] = useState(false);
  const {
    actionPending,
    approvals,
    connectionState,
    error,
    events,
    pauseRun,
    resolveApproval,
    resumeRun,
    runDetail,
    stopRun,
  } = useInterAgentGraph({
    initialApprovals,
    initialEvents,
    initialRunDetail,
    runId,
    visibilityPlane: GRAPH_VISIBILITY_PLANE,
  });

  const participants = runDetail?.participants || [];
  const edges = runDetail?.edges || [];
  const terminal = isTerminalRunStatus(runDetail?.run.status || "");
  const paused = runDetail?.run.status === "paused" || runDetail?.run.status === "recovering";
  const selectedParticipant =
    participants.find((participant) => participant.participant_id === selectedParticipantId) || null;
  const pendingApprovals = approvals.filter((approval) => approval.status === "pending");
  const latestSummary = useMemo(() => latestRunSummary(events), [events]);

  useEffect(() => {
    if (selectedParticipantId && participants.some((participant) => participant.participant_id === selectedParticipantId)) {
      return;
    }
    const orchestrator =
      participants.find((participant) => participant.participant_id === runDetail?.run.orchestrator_participant_id) ||
      participants.find((participant) => participant.kind === "orchestrator") ||
      participants[0] ||
      null;
    setSelectedParticipantId(orchestrator?.participant_id || null);
  }, [participants, runDetail?.run.orchestrator_participant_id, selectedParticipantId]);

  useEffect(() => {
    if (!selectedParticipantId) {
      setTranscript(null);
      setTranscriptError(null);
      setTranscriptLoading(false);
      return;
    }
    let cancelled = false;
    setTranscriptLoading(true);
    setTranscriptError(null);
    void getInterAgentParticipantTranscript(runId, selectedParticipantId, { limit: TRANSCRIPT_LIMIT })
      .then((payload) => {
        if (cancelled) {
          return;
        }
        setTranscript(payload);
      })
      .catch((loadError) => {
        if (cancelled) {
          return;
        }
        setTranscript(null);
        setTranscriptError(loadError instanceof Error ? loadError.message : "Unable to load participant transcript.");
      })
      .finally(() => {
        if (!cancelled) {
          setTranscriptLoading(false);
        }
      });
    return () => {
      cancelled = true;
    };
  }, [events.length, runId, selectedParticipantId, selectedParticipant?.updated_at]);

  return (
    <section className="chatapp-inter-agent-graph chatapp-agent-nodes-view" aria-label="Agent nodes view">
      <header className="chatapp-inter-agent-graph__header">
        <div className="chatapp-inter-agent-graph__title">
          <span className={`chatapp-inter-agent-graph__stream is-${connectionState}`} />
          <div>
            <span className="chatapp-inter-agent-graph__eyebrow">Agent nodes view</span>
            <h2>{runDetail ? runStatusLabel(runDetail.run.status) : "Loading run"}</h2>
            {latestSummary ? <p>{latestSummary}</p> : null}
          </div>
        </div>
        <div className="chatapp-inter-agent-graph__header-actions">
          <button
            className="chatapp-inter-agent-graph__button"
            disabled={!runDetail || terminal || paused || actionPending !== null}
            onClick={pauseRun}
            title="Pause run"
            type="button"
          >
            <span className="material-symbols-rounded" aria-hidden="true">pause</span>
            <span>Pause</span>
          </button>
          <button
            className="chatapp-inter-agent-graph__button"
            disabled={!runDetail || terminal || !paused || actionPending !== null}
            onClick={resumeRun}
            title="Resume run"
            type="button"
          >
            <span className="material-symbols-rounded" aria-hidden="true">play_arrow</span>
            <span>Resume</span>
          </button>
          <button
            className="chatapp-inter-agent-graph__button is-danger"
            disabled={!runDetail || terminal || actionPending !== null}
            onClick={stopRun}
            title="Stop run"
            type="button"
          >
            <span className="material-symbols-rounded" aria-hidden="true">stop</span>
            <span>Stop</span>
          </button>
          <button className="chatapp-inter-agent-graph__close" onClick={onClose} type="button" aria-label="Close Agent nodes">
            <span className="material-symbols-rounded" aria-hidden="true">close</span>
          </button>
        </div>
      </header>

      <div className="chatapp-inter-agent-graph__statusbar" aria-live="polite">
        <span>{participants.length} nodes</span>
        <span>{edges.length} connections</span>
        {pendingApprovals.length ? <span>{pendingApprovals.length} pending approvals</span> : null}
        {actionPending ? <span>{actionPending} pending</span> : null}
      </div>

      {error ? (
        <div className="chatapp-inter-agent-graph__notice is-error" role="alert">
          <span className="material-symbols-rounded" aria-hidden="true">error</span>
          <span>{error}</span>
        </div>
      ) : null}

      {!runDetail && connectionState === "connecting" ? (
        <div className="chatapp-inter-agent-graph__loading" role="status" aria-live="polite">
          <span className="chatapp-inter-agent-graph__loading-dot" />
          <span>Loading Agent nodes</span>
        </div>
      ) : null}

      <div className="chatapp-inter-agent-graph__body">
        <GraphCanvas
          onSelectParticipant={setSelectedParticipantId}
          runDetail={runDetail}
          selectedParticipantId={selectedParticipantId}
        />
        <ParticipantTranscript
          error={transcriptError}
          isLoading={transcriptLoading}
          participant={selectedParticipant}
          transcript={transcript}
        />
      </div>

      {pendingApprovals.length ? (
        <ApprovalShelf
          approvals={pendingApprovals}
          onSelectParticipant={setSelectedParticipantId}
          onResolveApproval={resolveApproval}
        />
      ) : null}
    </section>
  );
}

function GraphCanvas({
  onSelectParticipant,
  runDetail,
  selectedParticipantId,
}: {
  onSelectParticipant: (participantId: string) => void;
  runDetail: InterAgentRunDetail | null;
  selectedParticipantId: string | null;
}) {
  const participants = runDetail?.participants || [];
  const edges = runDetail?.edges || [];
  const layout = useMemo(() => graphBoardLayout(participants, runDetail?.run.orchestrator_participant_id), [
    participants,
    runDetail?.run.orchestrator_participant_id,
  ]);
  const edgeLinks = useMemo(() => graphEdgeLinks(edges, layout.nodesById), [edges, layout.nodesById]);
  const markerId = useMemo(() => svgFragmentId("chatapp-inter-agent-arrow", runDetail?.run.run_id || "run"), [
    runDetail?.run.run_id,
  ]);
  const boardHeightRem = Math.min(38, Math.max(21, layout.rowCount * 6.8 + 7));
  return (
    <div className="chatapp-inter-agent-graph__canvas" aria-label="Agent node map">
      {participants.length ? (
        <div
          className="chatapp-inter-agent-graph__board"
          style={{ "--graph-board-min-height": `${boardHeightRem}rem` } as CSSProperties}
        >
          <svg
            className="chatapp-inter-agent-graph__edge-layer"
            viewBox="0 0 100 100"
            preserveAspectRatio="none"
            aria-hidden="true"
          >
            <defs>
              <marker
                id={markerId}
                markerHeight="6"
                markerWidth="6"
                orient="auto"
                refX="5"
                refY="3"
                viewBox="0 0 6 6"
              >
                <path d="M0,0 L6,3 L0,6 Z" />
              </marker>
            </defs>
            {edgeLinks.map((link) => (
              <path
                className="chatapp-inter-agent-graph__edge-path"
                d={edgePath(link)}
                data-edge-id={link.edge.edge_id}
                key={link.edge.edge_id}
                markerEnd={`url(#${markerId})`}
                vectorEffect="non-scaling-stroke"
              />
            ))}
          </svg>
          {edgeLinks.map((link) => (
            <div
              className="chatapp-inter-agent-graph__edge-chip"
              key={link.edge.edge_id}
              style={
                { "--graph-edge-x": `${link.midpoint.x}%`, "--graph-edge-y": `${link.midpoint.y}%` } as CSSProperties
              }
              title={`${link.source.participant.label} -> ${link.target.participant.label}`}
            >
              <span className="material-symbols-rounded" aria-hidden="true">arrow_forward</span>
              <span>{edgeDisplayLabel(link.edge)}</span>
            </div>
          ))}
          {layout.nodes.map((node) => (
            <button
              className={`chatapp-inter-agent-graph__node is-${node.participant.status} ${
                selectedParticipantId === node.participant.participant_id ? "is-selected" : ""
              }`}
              data-participant-id={node.participant.participant_id}
              key={node.participant.participant_id}
              onClick={() => onSelectParticipant(node.participant.participant_id)}
              style={{ "--graph-node-x": `${node.x}%`, "--graph-node-y": `${node.y}%` } as CSSProperties}
              type="button"
            >
              <span className="material-symbols-rounded" aria-hidden="true">{participantIcon(node.participant.kind)}</span>
              <span className="chatapp-inter-agent-graph__node-copy">
                <strong>{node.participant.label}</strong>
                <span>{participantStatusLabel(node.participant.kind, node.participant.status)}</span>
              </span>
            </button>
          ))}
          {!edgeLinks.length && edges.length ? (
            <div className="chatapp-inter-agent-graph__edge-empty">Some connections are unavailable.</div>
          ) : null}
          {!edges.length ? <div className="chatapp-inter-agent-graph__edge-empty">No connections recorded.</div> : null}
        </div>
      ) : (
        <div className="chatapp-inter-agent-graph__empty">
          <span className="material-symbols-rounded" aria-hidden="true">account_tree</span>
          <span>No agent nodes yet.</span>
        </div>
      )}
    </div>
  );
}

function ParticipantTranscript({
  error,
  isLoading,
  participant,
  transcript,
}: {
  error: string | null;
  isLoading: boolean;
  participant: NonNullable<InterAgentRunDetail>["participants"][number] | null;
  transcript: InterAgentParticipantTranscriptPayload | null;
}) {
  return (
    <aside className="chatapp-inter-agent-graph__transcript" aria-label="Participant transcript">
      <div className="chatapp-inter-agent-graph__panel-title">
        <span>Participant transcript</span>
        {participant ? <small>{participant.status}</small> : null}
      </div>
      {participant ? (
        <div className="chatapp-inter-agent-graph__participant-heading">
          <span className="material-symbols-rounded" aria-hidden="true">{participantIcon(participant.kind)}</span>
          <div>
            <strong>{participant.label}</strong>
            <small>{participantStatusLabel(participant.kind, participant.status)}</small>
          </div>
        </div>
      ) : (
        <div className="chatapp-inter-agent-graph__empty is-compact">No participant selected.</div>
      )}
      {isLoading ? (
        <div className="chatapp-inter-agent-graph__loading is-compact" role="status" aria-live="polite">
          <span className="chatapp-inter-agent-graph__loading-dot" />
          <span>Loading transcript</span>
        </div>
      ) : null}
      {error ? (
        <div className="chatapp-inter-agent-graph__notice is-error" role="alert">
          <span className="material-symbols-rounded" aria-hidden="true">error</span>
          <span>{error}</span>
        </div>
      ) : null}
      {!isLoading && !error && transcript?.items.length ? (
        <ol className="chatapp-inter-agent-graph__transcript-list">
          {transcript.items.map((item) => (
            <li className={`is-${item.role} is-${item.kind}`} key={item.message_id}>
              <span className="material-symbols-rounded" aria-hidden="true">{transcriptItemIcon(item.kind, item.role)}</span>
              <div>
                <small>{transcriptItemLabel(item.kind, item.role, item.status)}</small>
                <p>{item.text}</p>
              </div>
            </li>
          ))}
        </ol>
      ) : null}
      {!isLoading && !error && participant && !transcript?.items.length ? (
        <div className="chatapp-inter-agent-graph__empty is-compact">No transcript yet.</div>
      ) : null}
    </aside>
  );
}

function ApprovalShelf({
  approvals,
  onResolveApproval,
  onSelectParticipant,
}: {
  approvals: InterAgentApprovalRecord[];
  onResolveApproval: (approvalId: string, approved: boolean) => Promise<void>;
  onSelectParticipant: (participantId: string) => void;
}) {
  const [resolvingApprovalId, setResolvingApprovalId] = useState<string | null>(null);

  async function resolveApproval(approvalId: string, approved: boolean) {
    setResolvingApprovalId(approvalId);
    try {
      await onResolveApproval(approvalId, approved);
    } finally {
      setResolvingApprovalId(null);
    }
  }

  return (
    <section className="chatapp-inter-agent-graph__approvals" aria-label="Pending approvals">
      {approvals.map((approval) => (
        <article className="chatapp-inter-agent-approval" key={approval.approval_id}>
          <div className="chatapp-inter-agent-approval__main">
            <button
              className={`chatapp-inter-agent-approval__risk is-${approval.risk_level}`}
              onClick={() => onSelectParticipant(approval.participant_id)}
              type="button"
            >
              {approval.risk_level}
            </button>
            <div className="chatapp-inter-agent-approval__copy">
              <strong>{approval.operation_kind}</strong>
              <p>{approval.summary}</p>
            </div>
          </div>
          <div className="chatapp-inter-agent-approval__actions">
            <button
              className="chatapp-inter-agent-approval__button"
              disabled={resolvingApprovalId === approval.approval_id}
              onClick={() => resolveApproval(approval.approval_id, false)}
              type="button"
            >
              Reject
            </button>
            <button
              className="chatapp-inter-agent-approval__button is-primary"
              disabled={resolvingApprovalId === approval.approval_id}
              onClick={() => resolveApproval(approval.approval_id, true)}
              type="button"
            >
              Approve
            </button>
          </div>
        </article>
      ))}
    </section>
  );
}

type GraphParticipant = NonNullable<InterAgentRunDetail>["participants"][number];
type GraphEdge = NonNullable<InterAgentRunDetail>["edges"][number];

type GraphBoardNode = {
  participant: GraphParticipant;
  x: number;
  y: number;
};

type GraphEdgeLink = {
  edge: GraphEdge;
  midpoint: { x: number; y: number };
  source: GraphBoardNode;
  target: GraphBoardNode;
};

function graphBoardLayout(
  participants: GraphParticipant[],
  orchestratorParticipantId?: string | null,
): { nodes: GraphBoardNode[]; nodesById: Map<string, GraphBoardNode>; rowCount: number } {
  if (!participants.length) {
    return { nodes: [], nodesById: new Map(), rowCount: 1 };
  }
  const orchestrators = participants.filter((participant) =>
    participant.participant_id === orchestratorParticipantId || participant.kind === "orchestrator"
  );
  const topParticipants = orchestrators.length ? orchestrators : [participants[0]];
  const topIds = new Set(topParticipants.map((participant) => participant.participant_id));
  const lowerParticipants = participants.filter((participant) => !topIds.has(participant.participant_id));
  const lowerRows = chunk(lowerParticipants, 3);
  const nodes: GraphBoardNode[] = [];
  const topY = lowerRows.length ? 15 : 50;

  topParticipants.forEach((participant, index) => {
    nodes.push({ participant, x: distributedX(index, topParticipants.length), y: topY });
  });
  lowerRows.forEach((row, rowIndex) => {
    const y = lowerRows.length === 1 ? 64 : 36 + (rowIndex * 46) / Math.max(1, lowerRows.length - 1);
    row.forEach((participant, index) => {
      nodes.push({ participant, x: distributedX(index, row.length), y });
    });
  });

  return {
    nodes,
    nodesById: new Map(nodes.map((node) => [node.participant.participant_id, node])),
    rowCount: Math.max(2, 1 + lowerRows.length),
  };
}

function graphEdgeLinks(edges: GraphEdge[], nodesById: Map<string, GraphBoardNode>): GraphEdgeLink[] {
  return edges.flatMap((edge) => {
    const source = nodesById.get(edge.source_id);
    const target = nodesById.get(edge.target_id);
    if (!source || !target) {
      return [];
    }
    return [
      {
        edge,
        midpoint: {
          x: (source.x + target.x) / 2,
          y: (source.y + target.y) / 2,
        },
        source,
        target,
      },
    ];
  });
}

function edgePath(link: GraphEdgeLink): string {
  const verticalDirection = link.target.y >= link.source.y ? 1 : -1;
  const startY = link.source.y + 8 * verticalDirection;
  const endY = link.target.y - 8 * verticalDirection;
  const verticalOffset = 18 * verticalDirection;
  return [
    `M ${link.source.x} ${startY}`,
    `C ${link.source.x} ${startY + verticalOffset}`,
    `${link.target.x} ${endY - verticalOffset}`,
    `${link.target.x} ${endY}`,
  ].join(" ");
}

function edgeDisplayLabel(edge: GraphEdge): string {
  return edge.label || edge.kind.replace(/_/g, " ");
}

function distributedX(index: number, count: number): number {
  if (count <= 1) {
    return 50;
  }
  const span = count === 2 ? 36 : 58;
  return 50 - span / 2 + (span * index) / Math.max(1, count - 1);
}

function chunk<T>(items: T[], size: number): T[][] {
  const chunks: T[][] = [];
  for (let index = 0; index < items.length; index += size) {
    chunks.push(items.slice(index, index + size));
  }
  return chunks;
}

function svgFragmentId(prefix: string, value: string): string {
  return `${prefix}-${String(value || "run").replace(/[^A-Za-z0-9_-]/g, "-")}`;
}

function latestRunSummary(events: InterAgentEventRecord[]): string {
  return (
    [...events]
      .reverse()
      .map((event) => eventSummary(event))
      .find((summary) => summary && summary !== "summary" && summary !== "detail" && summary !== "debug") || ""
  );
}

function participantStatusLabel(kind: string, status: string): string {
  return `${kind.replace(/_/g, " ")} - ${status.replace(/_/g, " ")}`;
}

function transcriptItemIcon(kind: string, role: string): string {
  if (kind === "artifact") {
    return "draft";
  }
  if (kind === "approval") {
    return "approval";
  }
  if (role === "user") {
    return "subdirectory_arrow_right";
  }
  if (role === "system") {
    return "info";
  }
  return "smart_toy";
}

function transcriptItemLabel(kind: string, role: string, status: string): string {
  const owner = role === "user" ? "Request" : role === "system" ? "System" : "Participant";
  const state = status ? ` - ${status.replace(/_/g, " ")}` : "";
  return `${owner} ${kind.replace(/_/g, " ")}${state}`;
}
