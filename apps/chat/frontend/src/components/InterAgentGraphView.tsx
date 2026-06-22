import { useCallback, useEffect, useMemo, useState, type CSSProperties, type MouseEvent } from "react";
import {
  Background,
  BackgroundVariant,
  Handle,
  MarkerType,
  Position,
  ReactFlow,
  ReactFlowProvider,
  useReactFlow,
  type Edge as ReactFlowEdge,
  type Node as ReactFlowNode,
  type NodeProps,
  type OnSelectionChangeParams,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
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
    () => {
      if (!selectedParticipantId) {
        return [];
      }
      const participantArtifacts = artifacts.filter((artifact) => artifact.participant_id === selectedParticipantId);
      const selectedIsOrchestrator =
        selectedParticipantId === runDetail?.run.orchestrator_participant_id || selectedParticipant?.kind === "orchestrator";
      if (!selectedIsOrchestrator) {
        return participantArtifacts;
      }
      const runLevelArtifacts = artifacts.filter((artifact) => !stringArtifactField(artifact.participant_id));
      return [...participantArtifacts, ...runLevelArtifacts];
    },
    [artifacts, runDetail?.run.orchestrator_participant_id, selectedParticipant?.kind, selectedParticipantId],
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
  const flowNodes = useMemo(
    () => graphFlowNodes(layout, selectedParticipantId, onSelectParticipant),
    [layout, onSelectParticipant, selectedParticipantId],
  );
  const flowEdges = useMemo(() => graphFlowEdges(edges, layout.nodesById), [edges, layout.nodesById]);
  const missingConnectionCount = Math.max(0, edges.length - flowEdges.length);
  const boardHeightRem = Math.min(38, Math.max(21, layout.height / 16 + 3));

  return (
    <div className="chatapp-inter-agent-graph__canvas" aria-label="Agent node map">
      {participants.length ? (
        <ReactFlowProvider initialWidth={760} initialHeight={420}>
          <GraphFlowCanvas
            boardHeightRem={boardHeightRem}
            edges={flowEdges}
            missingConnectionCount={missingConnectionCount}
            nodes={flowNodes}
            onSelectParticipant={onSelectParticipant}
            rawEdgeCount={edges.length}
          />
        </ReactFlowProvider>
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
  | { href: string; kind: "external" }
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
      return {
        href: appRouteShellHref(appTarget.appId, appTarget.appPage),
        kind: "app_page",
        appId: appTarget.appId,
        appPage: appTarget.appPage,
      };
    }
    const externalHref = externalArtifactHref(deepLink);
    if (externalHref) {
      return { href: externalHref, kind: "external" };
    }
    return null;
  }
  const workspacePath = stringArtifactField(artifact.workspace_relative_path);
  if (workspacePath) {
    const storageTarget = storageLinkTargetFromHref(workspacePath);
    if (storageTarget?.kind === "workspace_path") {
      return {
        href: storageShellHref(storageTarget.workspaceRelativePath),
        kind: "storage_path",
        workspaceRelativePath: storageTarget.workspaceRelativePath,
      };
    }
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

function appRouteShellHref(appId: string, appPage: string): string {
  const appIdSegment = encodeURIComponent(appId.trim());
  const page = appPage
    .split("/")
    .map((segment) => segment.trim())
    .filter(Boolean)
    .map(encodeURIComponent)
    .join("/");
  return page ? `/app/${appIdSegment}/${page}` : `/app/${appIdSegment}`;
}

function externalArtifactHref(value: string): string {
  try {
    const url = new URL(value.trim());
    if (url.protocol === "http:" || url.protocol === "https:") {
      return url.toString();
    }
  } catch {
    return "";
  }
  return "";
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
type AgentNodeData = Record<string, unknown> & {
  onSelect: (participantId: string) => void;
  participant: GraphParticipant;
};
type AgentEdgeData = Record<string, unknown> & {
  edge: GraphEdge;
};
type AgentFlowNode = ReactFlowNode<AgentNodeData, "agentParticipant">;
type AgentFlowEdge = ReactFlowEdge<AgentEdgeData, "smoothstep">;

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

const AGENT_NODE_TYPES = {
  agentParticipant: AgentParticipantNode,
};

function GraphFlowCanvas({
  boardHeightRem,
  edges,
  missingConnectionCount,
  nodes,
  onSelectParticipant,
  rawEdgeCount,
}: {
  boardHeightRem: number;
  edges: AgentFlowEdge[];
  missingConnectionCount: number;
  nodes: AgentFlowNode[];
  onSelectParticipant: (participantId: string) => void;
  rawEdgeCount: number;
}) {
  const reactFlow = useReactFlow<AgentFlowNode, AgentFlowEdge>();
  const fitToView = useCallback(() => {
    void reactFlow.fitView({ duration: 140, padding: 0.18 });
  }, [reactFlow]);
  const onNodeClick = useCallback(
    (_event: MouseEvent, node: AgentFlowNode) => {
      onSelectParticipant(node.data.participant.participant_id);
    },
    [onSelectParticipant],
  );
  const onSelectionChange = useCallback(
    ({ nodes: selectedNodes }: OnSelectionChangeParams<AgentFlowNode, AgentFlowEdge>) => {
      const participantId = selectedNodes[0]?.data.participant.participant_id || "";
      if (participantId) {
        onSelectParticipant(participantId);
      }
    },
    [onSelectParticipant],
  );

  useEffect(() => {
    if (!nodes.length) {
      return undefined;
    }
    const timeout = window.setTimeout(fitToView, 0);
    return () => window.clearTimeout(timeout);
  }, [edges.length, fitToView, nodes.length]);

  return (
    <div
      className="chatapp-inter-agent-graph__board"
      data-react-flow-agent-graph="true"
      style={{ "--graph-board-min-height": `${boardHeightRem}rem` } as CSSProperties}
    >
      <ReactFlow<AgentFlowNode, AgentFlowEdge>
        className="chatapp-inter-agent-graph__flow"
        colorMode="system"
        edges={edges}
        edgesFocusable={false}
        fitView
        fitViewOptions={{ padding: 0.18 }}
        maxZoom={GRAPH_MAX_ZOOM}
        minZoom={GRAPH_MIN_ZOOM}
        nodes={nodes}
        nodesConnectable={false}
        nodesDraggable={false}
        nodeTypes={AGENT_NODE_TYPES}
        onNodeClick={onNodeClick}
        onSelectionChange={onSelectionChange}
        panOnDrag
        panOnScroll
        preventScrolling
        proOptions={{ hideAttribution: true }}
        selectionOnDrag={false}
        zoomOnDoubleClick
        zoomOnPinch
        zoomOnScroll
      >
        <Background color="rgba(var(--maverick-contrast-rgb), 0.12)" gap={42} lineWidth={1} variant={BackgroundVariant.Lines} />
        <GraphFlowControls />
      </ReactFlow>
      {missingConnectionCount ? (
        <div className="chatapp-inter-agent-graph__edge-empty">Some connections are unavailable.</div>
      ) : null}
      {!rawEdgeCount ? <div className="chatapp-inter-agent-graph__edge-empty">No connections recorded.</div> : null}
    </div>
  );
}

function GraphFlowControls() {
  const reactFlow = useReactFlow<AgentFlowNode, AgentFlowEdge>();
  return (
    <div className="chatapp-inter-agent-graph__canvas-controls" aria-label="Canvas controls">
      <button aria-label="Zoom out" onClick={() => void reactFlow.zoomOut({ duration: 120 })} title="Zoom out" type="button">
        <span className="material-symbols-rounded" aria-hidden="true">remove</span>
      </button>
      <button aria-label="Fit graph" onClick={() => void reactFlow.fitView({ duration: 140, padding: 0.18 })} title="Fit graph" type="button">
        <span className="material-symbols-rounded" aria-hidden="true">fit_screen</span>
      </button>
      <button aria-label="Zoom in" onClick={() => void reactFlow.zoomIn({ duration: 120 })} title="Zoom in" type="button">
        <span className="material-symbols-rounded" aria-hidden="true">add</span>
      </button>
    </div>
  );
}

function AgentParticipantNode({ data, selected }: NodeProps) {
  const nodeData = data as AgentNodeData;
  const participant = nodeData.participant;
  return (
    <button
      className={`chatapp-inter-agent-graph__node is-${participant.status} ${selected ? "is-selected" : ""}`}
      data-participant-id={participant.participant_id}
      onClick={(event) => {
        event.stopPropagation();
        nodeData.onSelect(participant.participant_id);
      }}
      type="button"
    >
      <Handle className="chatapp-inter-agent-graph__handle" position={Position.Top} type="target" />
      <span className="material-symbols-rounded" aria-hidden="true">{participantIcon(participant.kind)}</span>
      <span className="chatapp-inter-agent-graph__node-copy">
        <strong>{participant.label}</strong>
        <span>{participantStatusLabel(participant.kind, participant.status)}</span>
      </span>
      <Handle className="chatapp-inter-agent-graph__handle" position={Position.Bottom} type="source" />
    </button>
  );
}

function graphFlowNodes(
  layout: GraphBoardLayout,
  selectedParticipantId: string | null,
  onSelectParticipant: (participantId: string) => void,
): AgentFlowNode[] {
  return layout.nodes.map((node) => ({
    data: {
      onSelect: onSelectParticipant,
      participant: node.participant,
    },
    draggable: false,
    id: node.participant.participant_id,
    position: {
      x: node.x - GRAPH_NODE_WIDTH / 2,
      y: node.y - GRAPH_NODE_HEIGHT / 2,
    },
    selectable: true,
    selected: selectedParticipantId === node.participant.participant_id,
    style: {
      height: GRAPH_NODE_HEIGHT,
      width: GRAPH_NODE_WIDTH,
    },
    type: "agentParticipant",
  }));
}

function graphFlowEdges(edges: GraphEdge[], nodesById: Map<string, GraphBoardNode>): AgentFlowEdge[] {
  return edges.flatMap((edge) => {
    const source = nodesById.get(edge.source_id);
    const target = nodesById.get(edge.target_id);
    if (!source || !target) {
      return [];
    }
    return [
      {
        animated: edge.status === "active" || edge.status === "running",
        className: "chatapp-inter-agent-graph__flow-edge",
        data: { edge },
        id: edge.edge_id,
        label: edgeDisplayLabel(edge),
        labelBgBorderRadius: 7,
        labelBgPadding: [7, 4],
        labelShowBg: true,
        markerEnd: { color: "var(--maverick-accent)", type: MarkerType.ArrowClosed },
        source: source.participant.participant_id,
        target: target.participant.participant_id,
        type: "smoothstep",
      } satisfies AgentFlowEdge,
    ];
  });
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
