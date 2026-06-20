import { useCallback, useEffect, useMemo, useRef, useState, type CSSProperties, type MouseEvent, type PointerEvent, type WheelEvent } from "react";
import {
  getInterAgentParticipantTranscript,
  type InterAgentApprovalRecord,
  type InterAgentArtifactRecord,
  type InterAgentEventRecord,
  type InterAgentParticipantTranscriptPayload,
  type InterAgentRunDetail,
  type InterAgentVisibilityPlane,
} from "../api/client";
import { useInterAgentGraph } from "../hooks/useInterAgentGraph";
import { eventSummary, isTerminalRunStatus, participantIcon, runStatusLabel } from "../lib/interAgentGraph";
import { openAppRouteInShell, openStoragePathInShell } from "../lib/shellNavigation";
import { storageAppPageShellHref, storageLinkTargetFromHref, storageShellHref } from "../lib/storageLinks";

type InterAgentGraphViewProps = {
  initialApprovals?: InterAgentApprovalRecord[];
  initialEvents?: InterAgentEventRecord[];
  initialRunDetail?: InterAgentRunDetail | null;
  onClose: () => void;
  runId: string;
};

const GRAPH_VISIBILITY_PLANE: InterAgentVisibilityPlane = "detail";
const TRANSCRIPT_LIMIT = 80;
const GRAPH_NODE_WIDTH = 220;
const GRAPH_NODE_HEIGHT = 72;
const GRAPH_COLUMN_GAP = 84;
const GRAPH_ROW_GAP = 128;
const GRAPH_PADDING = 56;
const GRAPH_MIN_ZOOM = 0.25;
const GRAPH_MAX_ZOOM = 1.6;

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
    artifacts,
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
  const selectedParticipantArtifacts = useMemo(
    () =>
      selectedParticipantId
        ? artifacts.filter((artifact) => artifact.participant_id === selectedParticipantId)
        : [],
    [artifacts, selectedParticipantId],
  );
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
          artifacts={selectedParticipantArtifacts}
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
  const {
    boardRef,
    fitToView,
    isPanning,
    onPointerDown,
    onPointerMove,
    onPointerUp,
    onWheel,
    transform,
    zoomBy,
  } = useGraphViewport(layout);
  const boardHeightRem = Math.min(38, Math.max(21, layout.height / 16 + 3));
  return (
    <div className="chatapp-inter-agent-graph__canvas" aria-label="Agent node map">
      {participants.length ? (
        <div
          className={`chatapp-inter-agent-graph__board ${isPanning ? "is-panning" : ""}`}
          onPointerDown={onPointerDown}
          onPointerMove={onPointerMove}
          onPointerUp={onPointerUp}
          onPointerCancel={onPointerUp}
          onWheel={onWheel}
          ref={boardRef}
          style={{ "--graph-board-min-height": `${boardHeightRem}rem` } as CSSProperties}
        >
          <div className="chatapp-inter-agent-graph__canvas-controls" aria-label="Canvas controls">
            <button aria-label="Zoom out" onClick={() => zoomBy(0.86)} title="Zoom out" type="button">
              <span className="material-symbols-rounded" aria-hidden="true">remove</span>
            </button>
            <button aria-label="Fit graph" onClick={fitToView} title="Fit graph" type="button">
              <span className="material-symbols-rounded" aria-hidden="true">fit_screen</span>
            </button>
            <button aria-label="Zoom in" onClick={() => zoomBy(1.14)} title="Zoom in" type="button">
              <span className="material-symbols-rounded" aria-hidden="true">add</span>
            </button>
          </div>
          <div
            className="chatapp-inter-agent-graph__surface"
            style={
              {
                "--graph-pan-x": `${transform.x}px`,
                "--graph-pan-y": `${transform.y}px`,
                "--graph-surface-height": `${layout.height}px`,
                "--graph-surface-width": `${layout.width}px`,
                "--graph-zoom": transform.zoom,
              } as CSSProperties
            }
          >
            <svg
              className="chatapp-inter-agent-graph__edge-layer"
              viewBox={`0 0 ${layout.width} ${layout.height}`}
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
                  { "--graph-edge-x": `${link.midpoint.x}px`, "--graph-edge-y": `${link.midpoint.y}px` } as CSSProperties
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
                style={
                  {
                    "--graph-node-width": `${GRAPH_NODE_WIDTH}px`,
                    "--graph-node-x": `${node.x}px`,
                    "--graph-node-y": `${node.y}px`,
                  } as CSSProperties
                }
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
  artifacts,
  error,
  isLoading,
  participant,
  transcript,
}: {
  artifacts: InterAgentArtifactRecord[];
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
      {!isLoading && !error && participant && artifacts.length ? <ParticipantArtifacts artifacts={artifacts} /> : null}
      {!isLoading && !error && participant && !transcript?.items.length && !artifacts.length ? (
        <div className="chatapp-inter-agent-graph__empty is-compact">No transcript yet.</div>
      ) : null}
    </aside>
  );
}

function ParticipantArtifacts({ artifacts }: { artifacts: InterAgentArtifactRecord[] }) {
  return (
    <section className="chatapp-inter-agent-graph__artifacts" aria-label="Participant artifacts">
      <div className="chatapp-inter-agent-graph__panel-title">
        <span>Artifacts</span>
        <small>{artifacts.length}</small>
      </div>
      <ul className="chatapp-inter-agent-graph__artifact-list">
        {artifacts.map((artifact) => (
          <li key={artifact.artifact_id || `${artifact.event_id}:${artifact.label}`}>
            <span className="material-symbols-rounded" aria-hidden="true">attach_file</span>
            <div>
              <ArtifactTitle artifact={artifact} />
              <small>{artifactMetadataLabel(artifact)}</small>
              {stringArtifactField(artifact.partial_output) ? <p>{stringArtifactField(artifact.partial_output)}</p> : null}
            </div>
          </li>
        ))}
      </ul>
    </section>
  );
}

function ArtifactTitle({ artifact }: { artifact: InterAgentArtifactRecord }) {
  const linkTarget = artifactLinkTarget(artifact);
  const label = stringArtifactField(artifact.label) || "Artifact";
  if (!linkTarget) {
    return <strong>{label}</strong>;
  }
  const isExternal = /^https?:\/\//i.test(linkTarget.href);
  return (
    <a
      href={linkTarget.href}
      onClick={(event) => handleArtifactLinkClick(event, linkTarget)}
      rel={isExternal ? "noopener noreferrer" : undefined}
      target={isExternal ? "_blank" : undefined}
    >
      {label}
    </a>
  );
}

type ArtifactLinkTarget =
  | { href: string; kind: "app_page"; appId: string; appPage: string }
  | { href: string; kind: "plain" }
  | { href: string; kind: "storage_page"; appPage: string }
  | { href: string; kind: "storage_path"; workspaceRelativePath: string };

function artifactLinkTarget(artifact: InterAgentArtifactRecord): ArtifactLinkTarget | null {
  const deepLink = stringArtifactField(artifact.deep_link);
  if (deepLink) {
    const storageTarget = storageLinkTargetFromHref(deepLink);
    if (storageTarget?.kind === "workspace_path") {
      return {
        href: storageShellHref(storageTarget.workspaceRelativePath),
        kind: "storage_path",
        workspaceRelativePath: storageTarget.workspaceRelativePath,
      };
    }
    if (storageTarget?.kind === "app_page") {
      return {
        href: storageAppPageShellHref(storageTarget.appPage),
        kind: "storage_page",
        appPage: storageTarget.appPage,
      };
    }
    const appTarget = appRouteTargetFromDeepLink(deepLink);
    if (appTarget) {
      return { href: deepLink, kind: "app_page", appId: appTarget.appId, appPage: appTarget.appPage };
    }
    return { href: deepLink, kind: "plain" };
  }
  const workspacePath = stringArtifactField(artifact.workspace_relative_path);
  if (workspacePath) {
    return { href: storageShellHref(workspacePath), kind: "storage_path", workspaceRelativePath: workspacePath };
  }
  const storageFileId =
    stringArtifactField(artifact.file_id) ||
    (stringArtifactField(artifact.app_id) === "storage" && stringArtifactField(artifact.entity_type) === "file"
      ? stringArtifactField(artifact.entity_id)
      : "");
  if (storageFileId) {
    return {
      href: storageAppPageShellHref(`files/${storageFileId}`),
      kind: "storage_page",
      appPage: `files/${storageFileId}`,
    };
  }
  return null;
}

function handleArtifactLinkClick(event: MouseEvent<HTMLAnchorElement>, target: ArtifactLinkTarget) {
  if (event.defaultPrevented || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey || event.button !== 0) {
    return;
  }
  if (target.kind === "storage_path" && openStoragePathInShell(target.workspaceRelativePath)) {
    event.preventDefault();
  }
  if (target.kind === "storage_page" && openAppRouteInShell("storage", target.appPage)) {
    event.preventDefault();
  }
  if (target.kind === "app_page" && openAppRouteInShell(target.appId, target.appPage)) {
    event.preventDefault();
  }
}

function appRouteTargetFromDeepLink(deepLink: string): { appId: string; appPage: string } | null {
  const match = deepLink.trim().match(/^\/apps?\/([^/?#]+)\/?([^?#]*)/);
  if (!match) {
    return null;
  }
  const appId = decodePathSegment(match[1]);
  const appPage = match[2]
    .split("/")
    .map(decodePathSegment)
    .filter(Boolean)
    .join("/");
  return appId ? { appId, appPage } : null;
}

function decodePathSegment(value: string): string {
  try {
    return decodeURIComponent(value);
  } catch {
    return value;
  }
}

function artifactMetadataLabel(artifact: InterAgentArtifactRecord): string {
  const status = runStatusLabel(stringArtifactField(artifact.status) || "created");
  const location =
    stringArtifactField(artifact.workspace_relative_path) ||
    stringArtifactField(artifact.relative_path) ||
    stringArtifactField(artifact.file_id);
  return location ? `${status} - ${location}` : status;
}

function stringArtifactField(value: unknown): string {
  return typeof value === "string" ? value.trim() : "";
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

type GraphBoardLayout = {
  height: number;
  nodes: GraphBoardNode[];
  nodesById: Map<string, GraphBoardNode>;
  width: number;
};

type GraphEdgeLink = {
  edge: GraphEdge;
  midpoint: { x: number; y: number };
  source: GraphBoardNode;
  target: GraphBoardNode;
};

type GraphTransform = {
  x: number;
  y: number;
  zoom: number;
};

function useGraphViewport(layout: GraphBoardLayout) {
  const boardRef = useRef<HTMLDivElement | null>(null);
  const dragRef = useRef<{ pointerId: number; startClientX: number; startClientY: number; startX: number; startY: number } | null>(null);
  const [isPanning, setIsPanning] = useState(false);
  const [transform, setTransform] = useState<GraphTransform>({ x: 24, y: 24, zoom: 1 });

  const fitToView = useCallback(() => {
    const board = boardRef.current;
    const rect = board?.getBoundingClientRect();
    const viewportWidth = rect?.width || board?.clientWidth || 720;
    const viewportHeight = rect?.height || board?.clientHeight || 420;
    const zoom = clamp(
      Math.min((viewportWidth - 32) / layout.width, (viewportHeight - 32) / layout.height),
      GRAPH_MIN_ZOOM,
      Math.min(1.2, GRAPH_MAX_ZOOM),
    );
    setTransform({
      x: Math.round((viewportWidth - layout.width * zoom) / 2),
      y: Math.round((viewportHeight - layout.height * zoom) / 2),
      zoom,
    });
  }, [layout.height, layout.width]);

  useEffect(() => {
    fitToView();
  }, [fitToView]);

  useEffect(() => {
    const board = boardRef.current;
    const ResizeObserverConstructor = typeof ResizeObserver === "undefined" ? null : ResizeObserver;
    if (!board || !ResizeObserverConstructor) {
      return;
    }
    const observer = new ResizeObserverConstructor(() => fitToView());
    observer.observe(board);
    return () => observer.disconnect();
  }, [fitToView]);

  const zoomBy = useCallback((factor: number, origin?: { x: number; y: number }) => {
    setTransform((current) => {
      const nextZoom = clamp(current.zoom * factor, GRAPH_MIN_ZOOM, GRAPH_MAX_ZOOM);
      const anchor = origin || {
        x: (boardRef.current?.getBoundingClientRect().width || 720) / 2,
        y: (boardRef.current?.getBoundingClientRect().height || 420) / 2,
      };
      const graphX = (anchor.x - current.x) / current.zoom;
      const graphY = (anchor.y - current.y) / current.zoom;
      return {
        x: anchor.x - graphX * nextZoom,
        y: anchor.y - graphY * nextZoom,
        zoom: nextZoom,
      };
    });
  }, []);

  const onPointerDown = useCallback((event: PointerEvent<HTMLDivElement>) => {
    const target = event.target instanceof Element ? event.target : null;
    if (target?.closest("button")) {
      return;
    }
    event.currentTarget.setPointerCapture(event.pointerId);
    dragRef.current = {
      pointerId: event.pointerId,
      startClientX: event.clientX,
      startClientY: event.clientY,
      startX: transform.x,
      startY: transform.y,
    };
    setIsPanning(true);
  }, [transform.x, transform.y]);

  const onPointerMove = useCallback((event: PointerEvent<HTMLDivElement>) => {
    const drag = dragRef.current;
    if (!drag || drag.pointerId !== event.pointerId) {
      return;
    }
    setTransform((current) => ({
      ...current,
      x: drag.startX + event.clientX - drag.startClientX,
      y: drag.startY + event.clientY - drag.startClientY,
    }));
  }, []);

  const onPointerUp = useCallback((event: PointerEvent<HTMLDivElement>) => {
    if (dragRef.current?.pointerId === event.pointerId) {
      dragRef.current = null;
      setIsPanning(false);
    }
  }, []);

  const onWheel = useCallback((event: WheelEvent<HTMLDivElement>) => {
    event.preventDefault();
    const rect = event.currentTarget.getBoundingClientRect();
    zoomBy(event.deltaY > 0 ? 0.9 : 1.1, {
      x: event.clientX - rect.left,
      y: event.clientY - rect.top,
    });
  }, [zoomBy]);

  return {
    boardRef,
    fitToView,
    isPanning,
    onPointerDown,
    onPointerMove,
    onPointerUp,
    onWheel,
    transform,
    zoomBy,
  };
}

function graphBoardLayout(
  participants: GraphParticipant[],
  orchestratorParticipantId?: string | null,
): GraphBoardLayout {
  if (!participants.length) {
    return { height: 320, nodes: [], nodesById: new Map(), width: 640 };
  }
  const orchestrators = participants.filter((participant) =>
    participant.participant_id === orchestratorParticipantId || participant.kind === "orchestrator"
  );
  const topParticipants = orchestrators.length ? orchestrators : [participants[0]];
  const topIds = new Set(topParticipants.map((participant) => participant.participant_id));
  const lowerParticipants = participants.filter((participant) => !topIds.has(participant.participant_id));
  const lowerColumns = Math.max(1, Math.min(4, Math.ceil(Math.sqrt(Math.max(1, lowerParticipants.length)))));
  const lowerRows = chunk(lowerParticipants, lowerColumns);
  const columnCount = Math.max(topParticipants.length, lowerColumns);
  const width = GRAPH_PADDING * 2 + columnCount * GRAPH_NODE_WIDTH + Math.max(0, columnCount - 1) * GRAPH_COLUMN_GAP;
  const rowCount = 1 + lowerRows.length;
  const height = GRAPH_PADDING * 2 + rowCount * GRAPH_NODE_HEIGHT + Math.max(0, rowCount - 1) * GRAPH_ROW_GAP;
  const nodes: GraphBoardNode[] = [];
  const topY = GRAPH_PADDING + GRAPH_NODE_HEIGHT / 2;

  topParticipants.forEach((participant, index) => {
    nodes.push({ participant, x: rowX(index, topParticipants.length, width), y: topY });
  });
  lowerRows.forEach((row, rowIndex) => {
    const y = topY + GRAPH_NODE_HEIGHT + GRAPH_ROW_GAP + rowIndex * (GRAPH_NODE_HEIGHT + GRAPH_ROW_GAP);
    row.forEach((participant, index) => {
      nodes.push({ participant, x: rowX(index, row.length, width), y });
    });
  });

  return {
    height,
    nodes,
    nodesById: new Map(nodes.map((node) => [node.participant.participant_id, node])),
    width,
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
  const startY = link.source.y + (GRAPH_NODE_HEIGHT / 2 + 10) * verticalDirection;
  const endY = link.target.y - (GRAPH_NODE_HEIGHT / 2 + 10) * verticalDirection;
  const verticalOffset = Math.min(96, Math.max(42, Math.abs(endY - startY) / 2)) * verticalDirection;
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

function rowX(index: number, count: number, boardWidth: number): number {
  if (count <= 1) {
    return boardWidth / 2;
  }
  const rowWidth = count * GRAPH_NODE_WIDTH + (count - 1) * GRAPH_COLUMN_GAP;
  const rowStart = (boardWidth - rowWidth) / 2 + GRAPH_NODE_WIDTH / 2;
  return rowStart + index * (GRAPH_NODE_WIDTH + GRAPH_COLUMN_GAP);
}

function chunk<T>(items: T[], size: number): T[][] {
  const chunks: T[][] = [];
  for (let index = 0; index < items.length; index += size) {
    chunks.push(items.slice(index, index + size));
  }
  return chunks;
}

function clamp(value: number, min: number, max: number): number {
  return Math.min(max, Math.max(min, value));
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
