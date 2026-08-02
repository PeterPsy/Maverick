import { useCallback, useEffect, useMemo, useState, type FormEvent, type MouseEvent } from "react";
import {
  applyNodeChanges,
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
  type NodeChange,
  type NodeProps,
  type OnSelectionChangeParams,
  type SmoothStepPathOptions,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import {
  getInterAgentParticipantTranscript,
  sendInterAgentDirective,
  type ChatMessage,
  type InterAgentApprovalRecord,
  type InterAgentArtifactRecord,
  type InterAgentEventRecord,
  type InterAgentParticipantTranscriptPayload,
  type InterAgentRunDetail,
  type InterAgentVisibilityPlane,
} from "../api/client";
import { useInterAgentGraph } from "../hooks/useInterAgentGraph";
import { participantIcon, runStatusLabel } from "../lib/interAgentGraph";
import { openAppRouteInShell, openStoragePathInShell } from "../lib/shellNavigation";
import { storageAppPageShellHref, storageLinkTargetFromHref, storageShellHref } from "../lib/storageLinks";
import { LiveBorderGlow } from "./LiveBorderGlow";
import { MessageList } from "./MessageList";

type InterAgentGraphViewProps = {
  initialApprovals?: InterAgentApprovalRecord[];
  initialEvents?: InterAgentEventRecord[];
  initialRunDetail?: InterAgentRunDetail | null;
  onClose: () => void;
  runId: string;
};

const GRAPH_VISIBILITY_PLANE: InterAgentVisibilityPlane = "detail";
const TRANSCRIPT_LIMIT = 80;
const GRAPH_NODE_WIDTH = 272;
const GRAPH_NODE_HEIGHT = 170;
const GRAPH_COLUMN_GAP = 104;
const GRAPH_ROW_GAP = 112;
const GRAPH_PADDING = 56;
const GRAPH_MAX_ROW_COLUMNS = 4;
const GRAPH_EDGE_DIRECT_OFFSET = 26;
const GRAPH_EDGE_LOOP_OFFSET = 96;
const GRAPH_EDGE_LOOP_MARGIN = 48;
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
  const [directiveText, setDirectiveText] = useState("");
  const [directiveStatus, setDirectiveStatus] = useState<"idle" | "sending" | "sent" | "error">("idle");
  const {
    approvals,
    artifacts,
    connectionState,
    error,
    events,
    resolveApproval,
    runDetail,
  } = useInterAgentGraph({
    initialApprovals,
    initialEvents,
    initialRunDetail,
    runId,
    visibilityPlane: GRAPH_VISIBILITY_PLANE,
  });

  const participants = runDetail?.participants || [];
  const selectedParticipant =
    participants.find((participant) => participant.participant_id === selectedParticipantId) || null;
  const hasSelectedParticipant = Boolean(selectedParticipant);
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
  const acceptsDirectives = Boolean(runDetail && !["completed", "failed", "cancelled"].includes(runDetail.run.status));

  async function submitDirective(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const text = directiveText.trim();
    if (!text || !acceptsDirectives || directiveStatus === "sending") {
      return;
    }
    setDirectiveStatus("sending");
    try {
      await sendInterAgentDirective(runId, {
        text,
        idempotency_key: `agent-nodes-directive:${crypto.randomUUID()}`,
      });
      setDirectiveText("");
      setDirectiveStatus("sent");
    } catch {
      setDirectiveStatus("error");
    }
  }

  useEffect(() => {
    if (selectedParticipantId && !participants.some((participant) => participant.participant_id === selectedParticipantId)) {
      setSelectedParticipantId(null);
    }
  }, [participants, selectedParticipantId]);

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
      <button className="chatapp-inter-agent-graph__back" onClick={onClose} type="button" aria-label="Back to chat">
        <span className="material-symbols-rounded" aria-hidden="true">arrow_back</span>
      </button>

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

      <div className={`chatapp-inter-agent-graph__body ${hasSelectedParticipant ? "has-transcript" : ""}`}>
        <GraphCanvas
          events={events}
          hasTranscript={hasSelectedParticipant}
          onSelectParticipant={setSelectedParticipantId}
          runDetail={runDetail}
          selectedParticipantId={selectedParticipantId}
        />
        {selectedParticipant ? (
          <ParticipantTranscript
            artifacts={selectedParticipantArtifacts}
            error={transcriptError}
            isLoading={transcriptLoading}
            onClose={() => setSelectedParticipantId(null)}
            participant={selectedParticipant}
            transcript={transcript}
          />
        ) : null}
      </div>

      {acceptsDirectives ? (
        <form className="chatapp-inter-agent-graph__directive" aria-label="Direct the orchestrator" onSubmit={submitDirective}>
          <textarea
            aria-label="Direction for the orchestrator"
            maxLength={6000}
            onChange={(event) => {
              setDirectiveText(event.target.value);
              setDirectiveStatus("idle");
            }}
            placeholder="Change direction, reduce scope, or prioritize speed…"
            rows={1}
            value={directiveText}
          />
          <button aria-label="Send direction" disabled={!directiveText.trim() || directiveStatus === "sending"} type="submit">
            <span className="material-symbols-rounded" aria-hidden="true">arrow_upward</span>
          </button>
          {directiveStatus === "sent" ? <span className="chatapp-inter-agent-graph__directive-status">Direction sent</span> : null}
          {directiveStatus === "error" ? <span className="chatapp-inter-agent-graph__directive-status is-error" role="alert">Direction failed</span> : null}
        </form>
      ) : null}

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
  events,
  hasTranscript,
  onSelectParticipant,
  runDetail,
  selectedParticipantId,
}: {
  events: InterAgentEventRecord[];
  hasTranscript: boolean;
  onSelectParticipant: (participantId: string) => void;
  runDetail: InterAgentRunDetail | null;
  selectedParticipantId: string | null;
}) {
  const participants = runDetail?.participants || [];
  const edges = runDetail?.edges || [];
  const layout = useMemo(
    () => graphBoardLayout(participants, edges, runDetail?.run.orchestrator_participant_id),
    [edges, participants, runDetail?.run.orchestrator_participant_id],
  );
  const activitiesByParticipantId = useMemo(
    () => participantActivityMap(participants, events),
    [events, participants],
  );
  const flowNodes = useMemo(
    () => graphFlowNodes(layout, activitiesByParticipantId, selectedParticipantId, onSelectParticipant),
    [activitiesByParticipantId, layout, onSelectParticipant, selectedParticipantId],
  );
  const flowEdges = useMemo(() => graphFlowEdges(edges, layout.nodesById), [edges, layout.nodesById]);
  const missingConnectionCount = Math.max(0, edges.length - flowEdges.length);

  return (
    <div className="chatapp-inter-agent-graph__canvas" aria-label="Agent node map">
      {participants.length ? (
        <ReactFlowProvider initialWidth={760} initialHeight={420}>
          <GraphFlowCanvas
            key={runDetail?.run.run_id || "inter-agent-graph"}
            edges={flowEdges}
            hasTranscript={hasTranscript}
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

function participantActivityMap(
  participants: GraphParticipant[],
  events: InterAgentEventRecord[],
): Map<string, ParticipantNodeActivity> {
  const latestEventsByParticipantId = new Map<string, InterAgentEventRecord>();
  const participantRunIds = new Map(participants.map((participant) => [participant.participant_id, participant.run_id]));
  for (const event of events) {
    const participantId = eventParticipantId(event);
    if (!participantId || participantRunIds.get(participantId) !== event.run_id) {
      continue;
    }
    const current = latestEventsByParticipantId.get(participantId);
    if (!current || event.sequence >= current.sequence) {
      latestEventsByParticipantId.set(participantId, event);
    }
  }
  return new Map(
    participants.map((participant) => {
      const activity =
        eventActivity(latestEventsByParticipantId.get(participant.participant_id)) ||
        participantStatusActivity(participant);
      return [participant.participant_id, activity];
    }),
  );
}

function eventActivity(event: InterAgentEventRecord | undefined): ParticipantNodeActivity | null {
  if (!event) {
    return null;
  }
  const payloadText = ["summary", "output_text", "text", "partial_output", "objective", "label", "operation_kind", "task"]
    .map((key) => stringRecordField(event.payload[key]))
    .find(Boolean);
  const eventLabel = event.event_type.split(".").at(-1)?.replace(/_/g, " ") || "Updated";
  const isToolEvent = event.event_type.includes("tool");
  return {
    kind: isToolEvent ? "tool" : "status",
    label: isToolEvent ? toolActivityLabel(event.event_type) : "",
    text: payloadText || eventLabel.charAt(0).toUpperCase() + eventLabel.slice(1),
  };
}

function toolActivityLabel(eventType: string): string {
  if (eventType.endsWith(".started")) {
    return "Tool in progress";
  }
  if (eventType.endsWith(".failed")) {
    return "Tool failed";
  }
  if (eventType.endsWith(".completed")) {
    return "Tool completed";
  }
  return "Tool activity";
}

function participantStatusActivity(participant: GraphParticipant): ParticipantNodeActivity {
  return {
    kind: "status",
    label: "Status",
    text: participant.status.replace(/_/g, " "),
  };
}

function eventParticipantId(event: InterAgentEventRecord): string {
  return stringRecordField(event.participant_id) || stringRecordField(event.payload.participant_id);
}

function stringRecordField(value: unknown): string {
  return typeof value === "string" ? value.trim() : "";
}

function activityIcon(kind: ParticipantNodeActivity["kind"]): string {
  if (kind === "tool") {
    return "build";
  }
  if (kind === "message") {
    return "chat_bubble";
  }
  if (kind === "step") {
    return "progress_activity";
  }
  return "info";
}

function isWorkingParticipantStatus(status: string): boolean {
  return status === "planning" || status === "running" || status === "reviewing" || status === "working";
}

function ParticipantTranscript({
  artifacts,
  error,
  isLoading,
  onClose,
  participant,
  transcript,
}: {
  artifacts: InterAgentArtifactRecord[];
  error: string | null;
  isLoading: boolean;
  onClose: () => void;
  participant: NonNullable<InterAgentRunDetail>["participants"][number];
  transcript: InterAgentParticipantTranscriptPayload | null;
}) {
  const inputSummary = participantInputSummary(transcript);
  const fallbackMessages = useMemo(() => participantFallbackMessages(transcript, participant), [participant, transcript]);
  const displayedMessages = fallbackMessages;
  const [expandedMessages, setExpandedMessages] = useState<Set<string>>(new Set());
  const [speakingMessageId, setSpeakingMessageId] = useState<string | null>(null);
  const latestToolMessageId =
    [...displayedMessages]
      .reverse()
      .find((message) => message.role === "tool" && (message.toolCalls?.length || message.toolCall))?.id || null;
  const copyMessage = useCallback(async (content: string) => {
    if (!content || !navigator.clipboard?.writeText) {
      return false;
    }
    await navigator.clipboard.writeText(content);
    return true;
  }, []);

  useEffect(() => {
    setExpandedMessages(new Set());
    setSpeakingMessageId(null);
  }, [participant.participant_id]);

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

  return (
    <aside className="chatapp-inter-agent-graph__transcript" aria-label={`${participant.label} transcript`}>
      <div className="chatapp-inter-agent-graph__transcript-header">
        <details className="chatapp-inter-agent-graph__transcript-title">
          <summary aria-label={`${participant.label} input summary`}>
            <span className="material-symbols-rounded" aria-hidden="true">
              {participantIcon(participant.kind)}
            </span>
            <span className="chatapp-inter-agent-graph__transcript-title-copy">
              <strong>{participant.label}</strong>
              <small>{participantStatusLabel(participant.kind, participant.status)}</small>
            </span>
            <span className="material-symbols-rounded chatapp-inter-agent-graph__transcript-title-caret" aria-hidden="true">
              expand_more
            </span>
          </summary>
          <div className="chatapp-inter-agent-graph__input-summary">
            <span>Input summary</span>
            <p>{inputSummary || "No input summary available."}</p>
          </div>
        </details>
        <button className="chatapp-inter-agent-graph__transcript-close" onClick={onClose} type="button" aria-label="Close transcript">
          <span className="material-symbols-rounded" aria-hidden="true">close</span>
        </button>
      </div>
      <div className="chatapp-inter-agent-graph__transcript-content">
        {isLoading && !displayedMessages.length ? (
          <div className="chatapp-inter-agent-graph__loading is-compact" role="status" aria-live="polite">
            <span className="chatapp-inter-agent-graph__loading-dot" />
            <span>Loading transcript</span>
          </div>
        ) : null}
        {error && !displayedMessages.length ? (
          <div className="chatapp-inter-agent-graph__notice is-error" role="alert">
            <span className="material-symbols-rounded" aria-hidden="true">error</span>
            <span>{error}</span>
          </div>
        ) : null}
        {displayedMessages.length ? (
          <div className="chatapp-inter-agent-graph__transcript-list">
            <MessageList
              expandedMessages={expandedMessages}
              latestToolMessageId={latestToolMessageId}
              mentionItems={[]}
              messages={displayedMessages}
              onActiveSpeechMessageChange={setSpeakingMessageId}
              onCopyMessage={copyMessage}
              onToggleExpanded={toggleExpanded}
              speakingMessageId={speakingMessageId}
              speechMaxTextChars={0}
              speechProviderAppId=""
              speechProviderAvailable={false}
              speechProviderQualityProfile=""
              speechProviderStreamingSupported={false}
            />
          </div>
        ) : null}
        {!isLoading && artifacts.length ? <ParticipantArtifacts artifacts={artifacts} /> : null}
        {!isLoading && !error && !displayedMessages.length && !artifacts.length ? (
          <div className="chatapp-inter-agent-graph__empty is-compact">No transcript yet.</div>
        ) : null}
      </div>
    </aside>
  );
}

function participantInputSummary(transcript: InterAgentParticipantTranscriptPayload | null): string {
  return (transcript?.items || [])
    .filter((item) => item.kind === "input" || item.role === "user")
    .map((item) => item.text.trim())
    .filter(Boolean)
    .join("\n\n");
}

function participantFallbackMessages(
  transcript: InterAgentParticipantTranscriptPayload | null,
  participant: GraphParticipant,
): ChatMessage[] {
  return (transcript?.items || [])
    .filter(
      (item) =>
        (item.role === "participant" && (item.kind === "output" || item.kind === "summary") && Boolean(item.text.trim())) ||
        (item.role === "tool" && item.kind === "tool" && Boolean(item.tool_call)),
    )
    .map((item) => {
      const source = {
        sourceLabel: participant.label,
        sourceParticipantId: participant.participant_id,
        sourceRunId: participant.run_id,
      };
      if (item.role === "tool" && item.tool_call) {
        const toolCall = {
          ...item.tool_call,
          createdAt: item.created_at,
        };
        return {
          id: item.message_id,
          role: "tool" as const,
          content: item.text || "Tool Used",
          createdAt: item.created_at,
          status: item.tool_call.status === "failed" ? "failed" as const : "complete" as const,
          toolCall,
          toolCalls: [toolCall],
          ...source,
        };
      }
      return {
        id: item.message_id,
        role: "agent" as const,
        content: item.text,
        createdAt: item.created_at,
        status: item.status === "failed" ? "failed" as const : "complete" as const,
        ...source,
      };
    });
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
type ParticipantNodeActivity = {
  kind: "message" | "status" | "step" | "tool";
  label: string;
  text: string;
};
type AgentNodeData = Record<string, unknown> & {
  activity: ParticipantNodeActivity;
  onSelect: (participantId: string) => void;
  participant: GraphParticipant;
};
type AgentEdgeData = Record<string, unknown> & {
  edge: GraphEdge;
};
type AgentFlowNode = ReactFlowNode<AgentNodeData, "agentParticipant">;
type AgentFlowEdge = ReactFlowEdge<AgentEdgeData, "smoothstep"> & {
  pathOptions?: SmoothStepPathOptions;
};

type GraphBoardNode = {
  columnIndex: number;
  depth: number;
  participant: GraphParticipant;
  rowIndex: number;
  x: number;
  y: number;
};

type GraphBoardLayout = {
  height: number;
  nodes: GraphBoardNode[];
  nodesById: Map<string, GraphBoardNode>;
  width: number;
};

type GraphHandleSide = "top" | "right" | "bottom" | "left";

type GraphEdgeRoute = {
  borderRadius: number;
  kind: "vertical" | "lateral" | "return";
  offset: number;
  sourceSide: GraphHandleSide;
  targetSide: GraphHandleSide;
};

type GraphBoardBounds = {
  maxX: number;
  minX: number;
};

const GRAPH_HANDLES: Array<{ position: Position; side: GraphHandleSide }> = [
  { position: Position.Top, side: "top" },
  { position: Position.Right, side: "right" },
  { position: Position.Bottom, side: "bottom" },
  { position: Position.Left, side: "left" },
];

const AGENT_NODE_TYPES = {
  agentParticipant: AgentParticipantNode,
};

function GraphFlowCanvas({
  edges,
  hasTranscript,
  missingConnectionCount,
  nodes,
  onSelectParticipant,
  rawEdgeCount,
}: {
  edges: AgentFlowEdge[];
  hasTranscript: boolean;
  missingConnectionCount: number;
  nodes: AgentFlowNode[];
  onSelectParticipant: (participantId: string) => void;
  rawEdgeCount: number;
}) {
  const reactFlow = useReactFlow<AgentFlowNode, AgentFlowEdge>();
  const [interactiveNodes, setInteractiveNodes] = useState<AgentFlowNode[]>(() => nodes);
  const fitToView = useCallback(() => {
    void reactFlow.fitView({ duration: 140, padding: 0.18 });
  }, [reactFlow]);
  const onNodesChange = useCallback((changes: NodeChange<AgentFlowNode>[]) => {
    setInteractiveNodes((currentNodes) => applyNodeChanges(changes, currentNodes));
  }, []);
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
    setInteractiveNodes((currentNodes) => mergeInteractiveGraphNodes(currentNodes, nodes));
  }, [nodes]);

  useEffect(() => {
    if (!nodes.length) {
      return undefined;
    }
    const timeout = window.setTimeout(fitToView, 0);
    return () => window.clearTimeout(timeout);
  }, [edges.length, fitToView, hasTranscript, nodes.length]);

  return (
    <div
      className="chatapp-inter-agent-graph__board"
      data-react-flow-agent-graph="true"
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
        nodes={interactiveNodes}
        nodesConnectable={false}
        nodesDraggable
        nodeTypes={AGENT_NODE_TYPES}
        onNodeClick={onNodeClick}
        onNodesChange={onNodesChange}
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
        <Background
          className="chatapp-inter-agent-graph__background"
          color="rgba(var(--maverick-contrast-rgb), 0.24)"
          gap={28}
          size={1.25}
          variant={BackgroundVariant.Dots}
        />
      </ReactFlow>
      {missingConnectionCount ? (
        <div className="chatapp-inter-agent-graph__edge-empty">Some connections are unavailable.</div>
      ) : null}
      {!rawEdgeCount ? <div className="chatapp-inter-agent-graph__edge-empty">No connections recorded.</div> : null}
    </div>
  );
}

function AgentParticipantNode({ data, selected }: NodeProps) {
  const nodeData = data as AgentNodeData;
  const participant = nodeData.participant;
  const isWorking = isWorkingParticipantStatus(participant.status);
  return (
    <div
      className={`chatapp-inter-agent-graph__node is-${participant.status} ${selected ? "is-selected" : ""} ${isWorking ? "is-working" : ""}`}
    >
      {GRAPH_HANDLES.map(({ position, side }) => (
        <Handle
          className={`chatapp-inter-agent-graph__handle is-${side}`}
          id={graphHandleId("target", side)}
          key={`target-${side}`}
          position={position}
          type="target"
        />
      ))}
      {isWorking ? <LiveBorderGlow className="chatapp-inter-agent-graph__node-glow" /> : null}
      <button
        className="chatapp-inter-agent-graph__node-select nodrag"
        data-participant-id={participant.participant_id}
        onClick={(event) => {
          event.stopPropagation();
          nodeData.onSelect(participant.participant_id);
        }}
        type="button"
      >
        <span className="material-symbols-rounded chatapp-inter-agent-graph__node-icon" aria-hidden="true">
          {participantIcon(participant.kind)}
        </span>
        <span className="chatapp-inter-agent-graph__node-copy">
          <strong>{participant.label}</strong>
          <span>{participantStatusLabel(participant.kind, participant.status)}</span>
        </span>
      </button>
      <div className="chatapp-inter-agent-graph__node-activity">
        {nodeData.activity.label ? (
          <div className="chatapp-inter-agent-graph__node-activity-heading">
            <span className="material-symbols-rounded" aria-hidden="true">{activityIcon(nodeData.activity.kind)}</span>
            <span>{nodeData.activity.label}</span>
          </div>
        ) : null}
        <p title={nodeData.activity.text}>{nodeData.activity.text}</p>
      </div>
      {GRAPH_HANDLES.map(({ position, side }) => (
        <Handle
          className={`chatapp-inter-agent-graph__handle is-${side}`}
          id={graphHandleId("source", side)}
          key={`source-${side}`}
          position={position}
          type="source"
        />
      ))}
    </div>
  );
}

function graphFlowNodes(
  layout: GraphBoardLayout,
  activitiesByParticipantId: Map<string, ParticipantNodeActivity>,
  selectedParticipantId: string | null,
  onSelectParticipant: (participantId: string) => void,
): AgentFlowNode[] {
  return layout.nodes.map((node) => ({
    data: {
      activity: activitiesByParticipantId.get(node.participant.participant_id) || participantStatusActivity(node.participant),
      onSelect: onSelectParticipant,
      participant: node.participant,
    },
    draggable: true,
    id: node.participant.participant_id,
    position: {
      x: node.x - GRAPH_NODE_WIDTH / 2,
      y: node.y - GRAPH_NODE_HEIGHT / 2,
    },
    selectable: true,
    selected: selectedParticipantId === node.participant.participant_id,
    style: {
      width: GRAPH_NODE_WIDTH,
    },
    type: "agentParticipant",
  }));
}

function mergeInteractiveGraphNodes(currentNodes: AgentFlowNode[], nextNodes: AgentFlowNode[]): AgentFlowNode[] {
  const currentNodesById = new Map(currentNodes.map((node) => [node.id, node]));
  return nextNodes.map((nextNode) => {
    const currentNode = currentNodesById.get(nextNode.id);
    if (!currentNode) {
      return nextNode;
    }
    return {
      ...nextNode,
      position: currentNode.position,
    };
  });
}

export function graphFlowEdges(edges: GraphEdge[], nodesById: Map<string, GraphBoardNode>): AgentFlowEdge[] {
  const bounds = graphBoardBounds(nodesById);
  return edges.flatMap((edge) => {
    const source = nodesById.get(edge.source_id);
    const target = nodesById.get(edge.target_id);
    if (!source || !target) {
      return [];
    }
    const route = graphEdgeRoute(edge, source, target, bounds);
    return [
      {
        animated: edge.status === "active" || edge.status === "running",
        className: `chatapp-inter-agent-graph__flow-edge is-${route.kind} is-${edge.status}`,
        data: { edge },
        id: edge.edge_id,
        interactionWidth: 18,
        label: edgeDisplayLabel(edge),
        labelBgBorderRadius: 7,
        labelBgPadding: [7, 4],
        labelShowBg: true,
        markerEnd: {
          color: "var(--chatapp-graph-edge-marker, var(--maverick-accent))",
          type: MarkerType.ArrowClosed,
        },
        pathOptions: {
          borderRadius: route.borderRadius,
          offset: route.offset,
        },
        source: source.participant.participant_id,
        sourceHandle: graphHandleId("source", route.sourceSide),
        target: target.participant.participant_id,
        targetHandle: graphHandleId("target", route.targetSide),
        type: "smoothstep",
        zIndex: route.kind === "return" ? 1 : 0,
      } satisfies AgentFlowEdge,
    ];
  });
}

export function graphBoardLayout(
  participants: GraphParticipant[],
  edges: GraphEdge[],
  orchestratorParticipantId?: string | null,
): GraphBoardLayout {
  if (!participants.length) {
    return { height: 320, nodes: [], nodesById: new Map(), width: 640 };
  }
  const sortedParticipants = [...participants].sort(compareGraphParticipants);
  const orchestrators = sortedParticipants.filter((participant) =>
    participant.participant_id === orchestratorParticipantId || participant.kind === "orchestrator"
  );
  const topParticipants = orchestrators.length ? orchestrators : [sortedParticipants[0]];
  const topIds = new Set(topParticipants.map((participant) => participant.participant_id));
  const depthById = graphParticipantDepths(sortedParticipants, edges, topIds);
  const rows = graphParticipantRows(sortedParticipants, depthById);
  const columnCount = Math.max(1, ...rows.map((row) => row.participants.length));
  const width = GRAPH_PADDING * 2 + columnCount * GRAPH_NODE_WIDTH + Math.max(0, columnCount - 1) * GRAPH_COLUMN_GAP;
  const rowCount = rows.length;
  const height = GRAPH_PADDING * 2 + rowCount * GRAPH_NODE_HEIGHT + Math.max(0, rowCount - 1) * GRAPH_ROW_GAP;
  const nodes: GraphBoardNode[] = [];

  rows.forEach((row, rowIndex) => {
    const y = GRAPH_PADDING + GRAPH_NODE_HEIGHT / 2 + rowIndex * (GRAPH_NODE_HEIGHT + GRAPH_ROW_GAP);
    row.participants.forEach((participant, columnIndex) => {
      nodes.push({
        columnIndex,
        depth: row.depth,
        participant,
        rowIndex,
        x: rowX(columnIndex, row.participants.length, width),
        y,
      });
    });
  });

  return {
    height,
    nodes,
    nodesById: new Map(nodes.map((node) => [node.participant.participant_id, node])),
    width,
  };
}

function graphParticipantDepths(
  participants: GraphParticipant[],
  edges: GraphEdge[],
  topIds: Set<string>,
): Map<string, number> {
  const participantIds = new Set(participants.map((participant) => participant.participant_id));
  const depthById = new Map<string, number>();
  const adjacency = new Map<string, string[]>();

  for (const topId of topIds) {
    if (participantIds.has(topId)) {
      depthById.set(topId, 0);
    }
  }

  for (const edge of edges) {
    if (!participantIds.has(edge.source_id) || !participantIds.has(edge.target_id) || topIds.has(edge.target_id)) {
      continue;
    }
    const targets = adjacency.get(edge.source_id) || [];
    if (!targets.includes(edge.target_id)) {
      targets.push(edge.target_id);
    }
    adjacency.set(edge.source_id, targets);
  }

  const queue = Array.from(depthById.keys());
  for (let index = 0; index < queue.length; index += 1) {
    const sourceId = queue[index];
    const sourceDepth = depthById.get(sourceId);
    if (sourceDepth === undefined) {
      continue;
    }
    for (const targetId of adjacency.get(sourceId) || []) {
      const nextDepth = sourceDepth + 1;
      const currentDepth = depthById.get(targetId);
      if (currentDepth === undefined || nextDepth < currentDepth) {
        depthById.set(targetId, nextDepth);
        queue.push(targetId);
      }
    }
  }

  participants.forEach((participant) => {
    if (!depthById.has(participant.participant_id)) {
      depthById.set(participant.participant_id, 1);
    }
  });

  return depthById;
}

function graphParticipantRows(
  participants: GraphParticipant[],
  depthById: Map<string, number>,
): Array<{ depth: number; participants: GraphParticipant[] }> {
  const participantsByDepth = new Map<number, GraphParticipant[]>();
  participants.forEach((participant) => {
    const depth = Math.max(0, depthById.get(participant.participant_id) || 0);
    const group = participantsByDepth.get(depth) || [];
    group.push(participant);
    participantsByDepth.set(depth, group);
  });

  return Array.from(participantsByDepth.entries())
    .sort(([leftDepth], [rightDepth]) => leftDepth - rightDepth)
    .flatMap(([depth, depthParticipants]) =>
      chunk(depthParticipants.sort(compareGraphParticipants), GRAPH_MAX_ROW_COLUMNS).map((row) => ({
        depth,
        participants: row,
      })),
    );
}

function graphEdgeRoute(
  edge: GraphEdge,
  source: GraphBoardNode,
  target: GraphBoardNode,
  bounds: GraphBoardBounds,
): GraphEdgeRoute {
  const dx = target.x - source.x;
  const dy = target.y - source.y;
  const returnsToEarlierLevel =
    target.depth < source.depth ||
    target.rowIndex < source.rowIndex ||
    (edge.kind === "produced" && target.participant.kind === "orchestrator");

  if (returnsToEarlierLevel) {
    const sourceRight = source.x + GRAPH_NODE_WIDTH / 2;
    const targetRight = target.x + GRAPH_NODE_WIDTH / 2;
    const sourceLeft = source.x - GRAPH_NODE_WIDTH / 2;
    const targetLeft = target.x - GRAPH_NODE_WIDTH / 2;
    const rightOffset = Math.max(sourceRight, targetRight) <= bounds.maxX
      ? bounds.maxX + GRAPH_EDGE_LOOP_MARGIN - Math.max(sourceRight, targetRight)
      : GRAPH_EDGE_LOOP_OFFSET;
    const leftOffset = Math.min(sourceLeft, targetLeft) >= bounds.minX
      ? Math.min(sourceLeft, targetLeft) - (bounds.minX - GRAPH_EDGE_LOOP_MARGIN)
      : GRAPH_EDGE_LOOP_OFFSET;
    const side: GraphHandleSide = rightOffset <= leftOffset ? "right" : "left";
    return {
      borderRadius: 24,
      kind: "return",
      offset: Math.ceil(Math.max(GRAPH_EDGE_LOOP_OFFSET, side === "right" ? rightOffset : leftOffset)),
      sourceSide: side,
      targetSide: side,
    };
  }

  if (Math.abs(dy) <= GRAPH_NODE_HEIGHT && Math.abs(dx) > GRAPH_NODE_WIDTH * 0.55) {
    return {
      borderRadius: 18,
      kind: "lateral",
      offset: GRAPH_EDGE_DIRECT_OFFSET,
      sourceSide: dx > 0 ? "right" : "left",
      targetSide: dx > 0 ? "left" : "right",
    };
  }

  if (dy >= 0) {
    return {
      borderRadius: 18,
      kind: "vertical",
      offset: GRAPH_EDGE_DIRECT_OFFSET,
      sourceSide: "bottom",
      targetSide: "top",
    };
  }

  return {
    borderRadius: 18,
    kind: "vertical",
    offset: GRAPH_EDGE_DIRECT_OFFSET,
    sourceSide: "top",
    targetSide: "bottom",
  };
}

function graphHandleId(type: "source" | "target", side: GraphHandleSide): string {
  return `${type}-${side}`;
}

function graphBoardBounds(nodesById: Map<string, GraphBoardNode>): GraphBoardBounds {
  const nodes = Array.from(nodesById.values());
  if (!nodes.length) {
    return { maxX: GRAPH_NODE_WIDTH, minX: 0 };
  }
  return {
    maxX: Math.max(...nodes.map((node) => node.x + GRAPH_NODE_WIDTH / 2)),
    minX: Math.min(...nodes.map((node) => node.x - GRAPH_NODE_WIDTH / 2)),
  };
}

function compareGraphParticipants(left: GraphParticipant, right: GraphParticipant): number {
  const leftIndex = typeof left.sequence_index === "number" ? left.sequence_index : Number.MAX_SAFE_INTEGER;
  const rightIndex = typeof right.sequence_index === "number" ? right.sequence_index : Number.MAX_SAFE_INTEGER;
  return leftIndex - rightIndex || left.participant_id.localeCompare(right.participant_id);
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

function participantStatusLabel(kind: string, status: string): string {
  return `${kind.replace(/_/g, " ")} - ${status.replace(/_/g, " ")}`;
}
