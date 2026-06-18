import { useEffect, useMemo, useState } from "react";
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
  onResolveApproval?: (approvalId: string, approved: boolean) => Promise<void>;
  runId: string;
};

export function InterAgentGraphView({
  initialApprovals = [],
  initialEvents = [],
  initialRunDetail = null,
  onClose,
  onResolveApproval = async () => undefined,
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
        <span>{runDetail?.participants.length || 0} participants</span>
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
        <Inspector item={selectedItem} onResolveApproval={onResolveApproval} />
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
  return (
    <div className="chatapp-inter-agent-graph__canvas" aria-label="Graph participants and edges">
      {participants.length ? (
        <div className="chatapp-inter-agent-graph__nodes">
          {participants.map((participant) => (
            <button
              className={`chatapp-inter-agent-graph__node is-${participant.status} ${selected?.kind === "participant" && selected.participantId === participant.participant_id ? "is-selected" : ""}`}
              key={participant.participant_id}
              onClick={() => onSelect({ id: `participant:${participant.participant_id}`, kind: "participant", participantId: participant.participant_id })}
              type="button"
            >
              <span className="material-symbols-rounded" aria-hidden="true">{participantIcon(participant.kind)}</span>
              <span className="chatapp-inter-agent-graph__node-copy">
                <strong>{participant.label}</strong>
                <span>{participant.kind} - {participant.status}</span>
              </span>
            </button>
          ))}
        </div>
      ) : (
        <div className="chatapp-inter-agent-graph__empty">
          <span className="material-symbols-rounded" aria-hidden="true">account_tree</span>
          <span>No participants yet.</span>
        </div>
      )}
      <div className="chatapp-inter-agent-graph__edges">
        {edges.map((edge) => (
          <button
            className={`chatapp-inter-agent-graph__edge ${selected?.kind === "edge" && selected.edgeId === edge.edge_id ? "is-selected" : ""}`}
            key={edge.edge_id}
            onClick={() => onSelect({ id: `edge:${edge.edge_id}`, kind: "edge", edgeId: edge.edge_id })}
            type="button"
          >
            <span>{edge.source_id}</span>
            <span className="material-symbols-rounded" aria-hidden="true">arrow_forward</span>
            <span>{edge.target_id}</span>
            <strong>{edge.label || edge.kind}</strong>
          </button>
        ))}
        {!edges.length && participants.length ? <div className="chatapp-inter-agent-graph__edge-empty">No explicit edges recorded.</div> : null}
      </div>
    </div>
  );
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
