import { useEffect, useMemo, useState, type CSSProperties } from "react";
import type {
  InterAgentApprovalRecord,
  InterAgentArtifactRecord,
  InterAgentEventRecord,
  InterAgentRunDetail,
  InterAgentVisibilityPlane,
} from "../api/client";
import { useInterAgentGraph } from "../hooks/useInterAgentGraph";
import {
  defaultGraphSelection,
  eventDisplayLabel,
  eventSummary,
  isTerminalRunStatus,
  participantIcon,
  runStatusLabel,
  selectionExists,
  type InterAgentGraphSelection,
} from "../lib/interAgentGraph";

type InterAgentGraphViewProps = {
  initialApprovals?: InterAgentApprovalRecord[];
  initialEvents?: InterAgentEventRecord[];
  initialRunDetail?: InterAgentRunDetail | null;
  onClose: () => void;
  runId: string;
};

export function InterAgentGraphView({
  initialApprovals = [],
  initialEvents = [],
  initialRunDetail = null,
  onClose,
  runId,
}: InterAgentGraphViewProps) {
  const [selected, setSelected] = useState<InterAgentGraphSelection | null>(null);
  const [visibilityPlane, setVisibilityPlane] = useState<InterAgentVisibilityPlane>("detail");
  const {
    actionPending,
    approvals,
    artifacts,
    connectionState,
    error,
    events,
    hasMoreHistory,
    isHistoryLoading,
    pauseRun,
    requestOlderHistory,
    resolveApproval,
    resumeRun,
    runDetail,
    stopRun,
  } = useInterAgentGraph({
    initialApprovals,
    initialEvents,
    initialRunDetail,
    runId,
    visibilityPlane,
  });

  const terminal = isTerminalRunStatus(runDetail?.run.status || "");
  const paused = runDetail?.run.status === "paused" || runDetail?.run.status === "recovering";
  const pendingApprovalCount = approvals.filter((approval) => approval.status === "pending").length;
  const selectedItem = useMemo(
    () => selectedItemFor(selected, runDetail, events, artifacts, approvals),
    [approvals, artifacts, events, runDetail, selected],
  );

  useEffect(() => {
    if (selectionExists(selected, runDetail, events, artifacts, approvals)) {
      return;
    }
    setSelected(defaultGraphSelection({ approvals, artifacts, events, runDetail }));
  }, [approvals, artifacts, events, runDetail, selected]);

  return (
    <section className="chatapp-inter-agent-graph" aria-label="Inter-agent graph">
      <header className="chatapp-inter-agent-graph__header">
        <div className="chatapp-inter-agent-graph__title">
          <span className={`chatapp-inter-agent-graph__stream is-${connectionState}`} />
          <div>
            <span className="chatapp-inter-agent-graph__eyebrow">Multi-agent graph</span>
            <h2>{runDetail ? runStatusLabel(runDetail.run.status) : "Loading run"}</h2>
          </div>
        </div>
        <div className="chatapp-inter-agent-graph__header-actions">
          <SegmentedVisibilityControl value={visibilityPlane} onChange={setVisibilityPlane} />
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
          <button className="chatapp-inter-agent-graph__close" onClick={onClose} type="button" aria-label="Close graph">
            <span className="material-symbols-rounded" aria-hidden="true">close</span>
          </button>
        </div>
      </header>

      <div className="chatapp-inter-agent-graph__statusbar" aria-live="polite">
        <span>{runDetail?.participants.length || 0} nodes</span>
        <span>{events.length} events</span>
        <span>{artifacts.length} artifacts</span>
        {pendingApprovalCount ? <span>{pendingApprovalCount} pending approvals</span> : null}
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
          <span>Loading graph</span>
        </div>
      ) : null}

      <div className="chatapp-inter-agent-graph__body">
        <GraphCanvas runDetail={runDetail} selected={selected} onSelect={setSelected} />
        <Timeline
          events={events}
          hasMoreHistory={hasMoreHistory}
          isHistoryLoading={isHistoryLoading}
          onLoadOlder={requestOlderHistory}
          onSelect={(eventId) => setSelected({ id: `event:${eventId}`, kind: "event", eventId })}
          selected={selected}
        />
        <Inspector item={selectedItem} onResolveApproval={resolveApproval} />
      </div>

      <ArtifactsStrip
        artifacts={artifacts}
        onSelect={(artifactId) => setSelected({ id: `artifact:${artifactId}`, kind: "artifact", artifactId })}
        selected={selected}
      />
    </section>
  );
}

function SegmentedVisibilityControl({
  onChange,
  value,
}: {
  onChange: (value: InterAgentVisibilityPlane) => void;
  value: InterAgentVisibilityPlane;
}) {
  return (
    <div className="chatapp-inter-agent-graph__segments" aria-label="Event visibility">
      {(["summary", "detail", "debug"] as const).map((plane) => (
        <button
          className={plane === value ? "is-active" : ""}
          key={plane}
          onClick={() => onChange(plane)}
          type="button"
        >
          {plane}
        </button>
      ))}
    </div>
  );
}

function GraphCanvas({
  onSelect,
  runDetail,
  selected,
}: {
  onSelect: (selection: InterAgentGraphSelection) => void;
  runDetail: InterAgentRunDetail | null;
  selected: InterAgentGraphSelection | null;
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
  const boardHeightRem = Math.min(33, Math.max(17, layout.rowCount * 6.2 + 5));
  return (
    <div className="chatapp-inter-agent-graph__canvas" aria-label="Graph participants and edges">
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
                className={`chatapp-inter-agent-graph__edge-path ${selected?.kind === "edge" && selected.edgeId === link.edge.edge_id ? "is-selected" : ""}`}
                d={edgePath(link)}
                data-edge-id={link.edge.edge_id}
                key={link.edge.edge_id}
                markerEnd={`url(#${markerId})`}
                vectorEffect="non-scaling-stroke"
              />
            ))}
          </svg>
          {edgeLinks.map((link) => (
            <button
              className={`chatapp-inter-agent-graph__edge-chip ${selected?.kind === "edge" && selected.edgeId === link.edge.edge_id ? "is-selected" : ""}`}
              key={link.edge.edge_id}
              onClick={() =>
                onSelect({ id: `edge:${link.edge.edge_id}`, kind: "edge", edgeId: link.edge.edge_id })
              }
              style={
                { "--graph-edge-x": `${link.midpoint.x}%`, "--graph-edge-y": `${link.midpoint.y}%` } as CSSProperties
              }
              title={`${link.source.participant.label} -> ${link.target.participant.label}`}
              type="button"
            >
              <span className="material-symbols-rounded" aria-hidden="true">arrow_forward</span>
              <span>{edgeDisplayLabel(link.edge)}</span>
            </button>
          ))}
          {layout.nodes.map((node) => (
            <button
              className={`chatapp-inter-agent-graph__node is-${node.participant.status} ${selected?.kind === "participant" && selected.participantId === node.participant.participant_id ? "is-selected" : ""}`}
              data-participant-id={node.participant.participant_id}
              key={node.participant.participant_id}
              onClick={() =>
                onSelect({
                  id: `participant:${node.participant.participant_id}`,
                  kind: "participant",
                  participantId: node.participant.participant_id,
                })
              }
              style={{ "--graph-node-x": `${node.x}%`, "--graph-node-y": `${node.y}%` } as CSSProperties}
              type="button"
            >
              <span className="material-symbols-rounded" aria-hidden="true">{participantIcon(node.participant.kind)}</span>
              <span className="chatapp-inter-agent-graph__node-copy">
                <strong>{node.participant.label}</strong>
                <span>{node.participant.kind} - {node.participant.status}</span>
              </span>
            </button>
          ))}
          {!edgeLinks.length && edges.length ? <div className="chatapp-inter-agent-graph__edge-empty">Some graph links reference unavailable participants.</div> : null}
          {!edges.length ? <div className="chatapp-inter-agent-graph__edge-empty">No graph links recorded.</div> : null}
        </div>
      ) : (
        <div className="chatapp-inter-agent-graph__empty">
          <span className="material-symbols-rounded" aria-hidden="true">account_tree</span>
          <span>No participants yet.</span>
        </div>
      )}
    </div>
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
  const topY = lowerRows.length ? 16 : 50;

  topParticipants.forEach((participant, index) => {
    nodes.push({ participant, x: distributedX(index, topParticipants.length), y: topY });
  });
  lowerRows.forEach((row, rowIndex) => {
    const y = lowerRows.length === 1 ? 64 : 40 + (rowIndex * 44) / Math.max(1, lowerRows.length - 1);
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
  const span = count === 2 ? 34 : 56;
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

function Timeline({
  events,
  hasMoreHistory,
  isHistoryLoading,
  onLoadOlder,
  onSelect,
  selected,
}: {
  events: InterAgentEventRecord[];
  hasMoreHistory: boolean;
  isHistoryLoading: boolean;
  onLoadOlder: () => void;
  onSelect: (eventId: string) => void;
  selected: InterAgentGraphSelection | null;
}) {
  return (
    <aside className="chatapp-inter-agent-graph__timeline" aria-label="Timeline">
      <div className="chatapp-inter-agent-graph__panel-title">
        <span>Timeline</span>
        {hasMoreHistory ? (
          <button disabled={isHistoryLoading} onClick={onLoadOlder} type="button">
            {isHistoryLoading ? "Loading" : "Older"}
          </button>
        ) : null}
      </div>
      <ol>
        {events.map((event) => (
          <li key={event.event_id}>
            <button
              className={selected?.kind === "event" && selected.eventId === event.event_id ? "is-selected" : ""}
              onClick={() => onSelect(event.event_id)}
              type="button"
            >
              <span>{eventDisplayLabel(event)}</span>
              <strong>{eventSummary(event)}</strong>
              <small>{event.visibility_plane} - #{event.sequence}</small>
            </button>
          </li>
        ))}
      </ol>
      {!events.length ? <div className="chatapp-inter-agent-graph__empty is-compact">No events for this filter.</div> : null}
    </aside>
  );
}

function ArtifactsStrip({
  artifacts,
  onSelect,
  selected,
}: {
  artifacts: InterAgentArtifactRecord[];
  onSelect: (artifactId: string) => void;
  selected: InterAgentGraphSelection | null;
}) {
  return (
    <section className="chatapp-inter-agent-graph__artifacts" aria-label="Artifacts">
      <div className="chatapp-inter-agent-graph__panel-title">
        <span>Artifacts</span>
        <small>{artifacts.length}</small>
      </div>
      <div className="chatapp-inter-agent-graph__artifact-list">
        {artifacts.map((artifact) => (
          <button
            className={selected?.kind === "artifact" && selected.artifactId === artifact.artifact_id ? "is-selected" : ""}
            key={artifact.artifact_id}
            onClick={() => onSelect(artifact.artifact_id)}
            type="button"
          >
            <span className="material-symbols-rounded" aria-hidden="true">draft</span>
            <span>
              <strong>{artifact.label}</strong>
              <small>{artifact.status}</small>
            </span>
          </button>
        ))}
        {!artifacts.length ? <div className="chatapp-inter-agent-graph__empty is-compact">No artifacts recorded.</div> : null}
      </div>
    </section>
  );
}

type InspectorItem =
  | { kind: "participant"; value: NonNullable<InterAgentRunDetail>["participants"][number] }
  | { kind: "edge"; value: NonNullable<InterAgentRunDetail>["edges"][number] }
  | { kind: "event"; value: InterAgentEventRecord }
  | { kind: "artifact"; value: InterAgentArtifactRecord }
  | { kind: "approval"; value: InterAgentApprovalRecord }
  | null;

function Inspector({
  item,
  onResolveApproval,
}: {
  item: InspectorItem;
  onResolveApproval: (approvalId: string, approved: boolean) => Promise<void>;
}) {
  const [resolving, setResolving] = useState(false);

  async function resolveApproval(approvalId: string, approved: boolean) {
    setResolving(true);
    try {
      await onResolveApproval(approvalId, approved);
    } finally {
      setResolving(false);
    }
  }

  return (
    <aside className="chatapp-inter-agent-graph__inspector" aria-label="Inspector">
      <div className="chatapp-inter-agent-graph__panel-title">
        <span>Inspector</span>
      </div>
      {!item ? <div className="chatapp-inter-agent-graph__empty is-compact">Select a node, event, or artifact.</div> : null}
      {item?.kind === "participant" ? (
        <InspectorBlock
          title={item.value.label}
          rows={[
            ["Kind", item.value.kind],
            ["Status", item.value.status],
            ["Execution", item.value.execution_mode],
            ["Runtime session", item.value.runtime_session_id || "none"],
          ]}
        />
      ) : null}
      {item?.kind === "edge" ? (
        <InspectorBlock
          title={item.value.label || item.value.kind}
          rows={[
            ["Source", item.value.source_id],
            ["Target", item.value.target_id],
            ["Status", item.value.status],
          ]}
        />
      ) : null}
      {item?.kind === "event" ? (
        <InspectorBlock
          title={eventDisplayLabel(item.value)}
          rows={[
            ["Summary", eventSummary(item.value)],
            ["Participant", item.value.participant_id || "run"],
            ["Visibility", item.value.visibility_plane],
            ["Sequence", String(item.value.sequence)],
          ]}
          payload={item.value.payload}
        />
      ) : null}
      {item?.kind === "artifact" ? (
        <InspectorBlock
          title={item.value.label}
          rows={[
            ["Status", item.value.status],
            ["Participant", item.value.participant_id || "unknown"],
            ["Path", item.value.workspace_relative_path || item.value.relative_path || item.value.file_id || "not linked"],
          ]}
          payload={item.value.partial_output ? { partial_output: item.value.partial_output } : undefined}
        />
      ) : null}
      {item?.kind === "approval" ? (
        <>
          <InspectorBlock
            title={item.value.operation_kind}
            rows={[
              ["Risk", item.value.risk_level],
              ["Status", item.value.status],
              ["Participant", item.value.participant_id],
              ["Summary", item.value.summary],
            ]}
          />
          {item.value.status === "pending" ? (
            <div className="chatapp-inter-agent-graph__approval-actions">
              <button disabled={resolving} onClick={() => resolveApproval(item.value.approval_id, false)} type="button">Reject</button>
              <button disabled={resolving} onClick={() => resolveApproval(item.value.approval_id, true)} type="button">Approve</button>
            </div>
          ) : null}
        </>
      ) : null}
    </aside>
  );
}

function InspectorBlock({
  payload,
  rows,
  title,
}: {
  payload?: Record<string, unknown>;
  rows: Array<[string, string]>;
  title: string;
}) {
  return (
    <div className="chatapp-inter-agent-graph__inspect-block">
      <h3>{title}</h3>
      <dl>
        {rows.map(([label, value]) => (
          <div key={label}>
            <dt>{label}</dt>
            <dd>{value}</dd>
          </div>
        ))}
      </dl>
      {payload ? <pre>{JSON.stringify(payload, null, 2)}</pre> : null}
    </div>
  );
}

function selectedItemFor(
  selection: InterAgentGraphSelection | null,
  runDetail: InterAgentRunDetail | null,
  events: InterAgentEventRecord[],
  artifacts: InterAgentArtifactRecord[],
  approvals: InterAgentApprovalRecord[],
): InspectorItem {
  if (!selection) {
    return null;
  }
  if (selection.kind === "participant") {
    const value = runDetail?.participants.find((participant) => participant.participant_id === selection.participantId);
    return value ? { kind: "participant", value } : null;
  }
  if (selection.kind === "edge") {
    const value = runDetail?.edges.find((edge) => edge.edge_id === selection.edgeId);
    return value ? { kind: "edge", value } : null;
  }
  if (selection.kind === "event") {
    const value = events.find((event) => event.event_id === selection.eventId);
    return value ? { kind: "event", value } : null;
  }
  if (selection.kind === "artifact") {
    const value = artifacts.find((artifact) => artifact.artifact_id === selection.artifactId);
    return value ? { kind: "artifact", value } : null;
  }
  const value = approvals.find((approval) => approval.approval_id === selection.approvalId);
  return value ? { kind: "approval", value } : null;
}
