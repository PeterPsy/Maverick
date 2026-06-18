import { useCallback, useEffect, useRef, useState } from "react";
import {
  closeInterAgentRun,
  getInterAgentRun,
  interAgentWebSocketUrl,
  interruptInterAgentRun,
  listInterAgentRunApprovals,
  listInterAgentRunArtifacts,
  listInterAgentRunEvents,
  resumeInterAgentRun,
  type InterAgentApprovalRecord,
  type InterAgentArtifactRecord,
  type InterAgentEventRecord,
  type InterAgentRunDetail,
  type InterAgentVisibilityPlane,
  type InterAgentWebSocketFrame,
} from "../api/client";
import {
  artifactsFromInterAgentEvents,
  firstInterAgentEventId,
  isTerminalRunStatus,
  lastInterAgentEventId,
  mergeInterAgentArtifacts,
  mergeInterAgentEvents,
} from "../lib/interAgentGraph";

type InterAgentConnectionState = "connecting" | "live" | "reconnecting" | "unavailable";
type InterAgentRunAction = "pause" | "resume" | "stop" | null;

export type UseInterAgentGraphArgs = {
  initialApprovals?: InterAgentApprovalRecord[];
  initialEvents?: InterAgentEventRecord[];
  initialRunDetail?: InterAgentRunDetail | null;
  runId: string;
  visibilityPlane: InterAgentVisibilityPlane;
};

export function useInterAgentGraph({
  initialApprovals = [],
  initialEvents = [],
  initialRunDetail = null,
  runId,
  visibilityPlane,
}: UseInterAgentGraphArgs) {
  const seededInitialEvents = eventsForVisibility(initialEvents, visibilityPlane);
  const [actionPending, setActionPending] = useState<InterAgentRunAction>(null);
  const [approvals, setApprovals] = useState<InterAgentApprovalRecord[]>(initialApprovals);
  const [artifacts, setArtifacts] = useState<InterAgentArtifactRecord[]>(artifactsFromInterAgentEvents(seededInitialEvents));
  const [connectionState, setConnectionState] = useState<InterAgentConnectionState>("connecting");
  const [error, setError] = useState<string | null>(null);
  const [events, setEvents] = useState<InterAgentEventRecord[]>(seededInitialEvents);
  const [hasMoreHistory, setHasMoreHistory] = useState(false);
  const [isHistoryLoading, setIsHistoryLoading] = useState(false);
  const [runDetail, setRunDetail] = useState<InterAgentRunDetail | null>(initialRunDetail);
  const eventsRef = useRef(seededInitialEvents);
  const historyRequestTimerRef = useRef<number | null>(null);
  const oldestEventIdRef = useRef<string | null>(firstInterAgentEventId(seededInitialEvents));
  const socketRef = useRef<WebSocket | null>(null);

  const clearHistoryRequestTimer = useCallback(() => {
    if (historyRequestTimerRef.current !== null) {
      window.clearTimeout(historyRequestTimerRef.current);
      historyRequestTimerRef.current = null;
    }
  }, []);

  useEffect(() => {
    const seededEvents = eventsForVisibility(initialEvents, visibilityPlane);
    clearHistoryRequestTimer();
    eventsRef.current = seededEvents;
    oldestEventIdRef.current = firstInterAgentEventId(seededEvents);
    setActionPending(null);
    setApprovals(initialApprovals);
    setArtifacts(artifactsFromInterAgentEvents(seededEvents));
    setConnectionState("connecting");
    setError(null);
    setEvents(seededEvents);
    setHasMoreHistory(false);
    setIsHistoryLoading(false);
    setRunDetail(initialRunDetail);
  }, [clearHistoryRequestTimer, runId, visibilityPlane]);

  const applyEvents = useCallback((incoming: InterAgentEventRecord[], oldestEventId?: string | null) => {
    if (!incoming.length) {
      if (oldestEventId) {
        oldestEventIdRef.current = oldestEventId;
      }
      return;
    }
    setEvents((current) => {
      const merged = mergeInterAgentEvents(current, incoming);
      eventsRef.current = merged;
      oldestEventIdRef.current = oldestEventId || firstInterAgentEventId(merged);
      return merged;
    });
    setArtifacts((current) => mergeInterAgentArtifacts(current, artifactsFromInterAgentEvents(incoming)));
    setRunDetail((current) => applyRunEventUpdates(current, incoming));
  }, []);

  const refreshRecords = useCallback(async () => {
    try {
      const [detail, eventPage, approvalsPayload, artifactPage] = await Promise.all([
        getInterAgentRun(runId),
        listInterAgentRunEvents(runId, { visibilityPlane, limit: 240 }),
        listInterAgentRunApprovals(runId),
        listInterAgentRunArtifacts(runId, { visibilityPlane, limit: 240 }),
      ]);
      setRunDetail(detail);
      setApprovals(approvalsPayload.items);
      setArtifacts((current) => mergeInterAgentArtifacts(current, artifactPage.items));
      setHasMoreHistory(eventPage.has_more_before === true);
      applyEvents(eventPage.items, eventPage.oldest_event_id);
      setError(null);
    } catch (loadError) {
      setError(loadError instanceof Error ? loadError.message : "Unable to load graph.");
    }
  }, [applyEvents, runId, visibilityPlane]);

  useEffect(() => {
    void refreshRecords();
  }, [refreshRecords]);

  useEffect(() => {
    if (typeof WebSocket === "undefined") {
      setConnectionState("unavailable");
      setError("Inter-agent WebSocket is unavailable.");
      return;
    }
    let cancelled = false;
    let reconnectTimer: number | null = null;
    let heartbeatTimer: number | null = null;
    let receivedInitialSnapshot = false;
    let lastFrameAt = Date.now();
    let lastEventId = lastInterAgentEventId(eventsRef.current);

    function connectWebSocket() {
      if (cancelled) {
        return;
      }
      setConnectionState(receivedInitialSnapshot ? "reconnecting" : "connecting");
      const replayCursor = receivedInitialSnapshot ? lastEventId : null;
      const socket = new WebSocket(interAgentWebSocketUrl(runId, { lastEventId: replayCursor, visibilityPlane, initialEventLimit: 240 }));
      socketRef.current = socket;
      socket.onopen = () => {
        lastFrameAt = Date.now();
        setError(null);
        startHeartbeatWatchdog();
      };
      socket.onmessage = (event) => {
        lastFrameAt = Date.now();
        try {
          const frame = JSON.parse(event.data) as InterAgentWebSocketFrame;
          if (frame.type === "inter_agent.snapshot") {
            receivedInitialSnapshot = true;
            setConnectionState("live");
            setRunDetail(frame.run_detail);
            setApprovals(frame.approvals || []);
            setArtifacts((current) => mergeInterAgentArtifacts(current, frame.artifacts || []));
            setHasMoreHistory(frame.has_more_before === true);
            lastEventId = frame.last_event_id || lastEventId;
            applyEvents(frame.events || [], frame.oldest_event_id);
            if (!frame.events?.length) {
              oldestEventIdRef.current = frame.oldest_event_id || oldestEventIdRef.current;
            }
            return;
          }
          if (frame.type === "inter_agent.history.page") {
            clearHistoryRequestTimer();
            setHasMoreHistory(frame.has_more_before === true);
            setArtifacts((current) => mergeInterAgentArtifacts(current, frame.artifacts || []));
            applyEvents(frame.events || [], frame.oldest_event_id);
            setIsHistoryLoading(false);
            return;
          }
          if (frame.type === "inter_agent.event") {
            lastEventId = frame.event.event_id;
            applyEvents([frame.event]);
          }
        } catch (parseError) {
          setError(parseError instanceof Error ? parseError.message : "Unable to parse inter-agent graph frame.");
        }
      };
      socket.onerror = () => {
        if (!receivedInitialSnapshot) {
          setError("Inter-agent WebSocket is unavailable.");
        }
      };
      socket.onclose = (event) => {
        stopHeartbeatWatchdog();
        if (socketRef.current === socket) {
          socketRef.current = null;
        }
        if (cancelled) {
          return;
        }
        if (event.code === 4401 || event.code === 4404 || event.code === 4408) {
          setConnectionState("unavailable");
          setError("Graph stream is not available for this run.");
          return;
        }
        setConnectionState("reconnecting");
        reconnectTimer = window.setTimeout(connectWebSocket, 800);
      };
    }

    function startHeartbeatWatchdog() {
      stopHeartbeatWatchdog();
      heartbeatTimer = window.setInterval(() => {
        if (Date.now() - lastFrameAt > 60000) {
          socketRef.current?.close();
        }
      }, 10000);
    }

    function stopHeartbeatWatchdog() {
      if (heartbeatTimer !== null) {
        window.clearInterval(heartbeatTimer);
        heartbeatTimer = null;
      }
    }

    connectWebSocket();

    return () => {
      cancelled = true;
      if (reconnectTimer !== null) {
        window.clearTimeout(reconnectTimer);
      }
      clearHistoryRequestTimer();
      stopHeartbeatWatchdog();
      socketRef.current?.close();
      socketRef.current = null;
    };
  }, [applyEvents, clearHistoryRequestTimer, runId, visibilityPlane]);

  const requestOlderHistory = useCallback(() => {
    if (!hasMoreHistory || isHistoryLoading) {
      return;
    }
    const beforeEventId = oldestEventIdRef.current;
    const socket = socketRef.current;
    if (!beforeEventId || !socket || socket.readyState !== WebSocket.OPEN) {
      setIsHistoryLoading(false);
      return;
    }
    clearHistoryRequestTimer();
    setIsHistoryLoading(true);
    try {
      socket.send(
        JSON.stringify({
          type: "inter_agent.history.before",
          before_event_id: beforeEventId,
          limit: 120,
        }),
      );
      historyRequestTimerRef.current = window.setTimeout(() => {
        historyRequestTimerRef.current = null;
        setIsHistoryLoading(false);
      }, 8000);
    } catch (sendError) {
      setIsHistoryLoading(false);
      setError(sendError instanceof Error ? sendError.message : "Unable to request older graph history.");
    }
  }, [clearHistoryRequestTimer, hasMoreHistory, isHistoryLoading]);

  const pauseRun = useCallback(async () => {
    if (!runDetail || isTerminalRunStatus(runDetail.run.status)) {
      return;
    }
    setActionPending("pause");
    try {
      const result = await interruptInterAgentRun(runId, { reason: "chat_graph_pause" });
      setRunDetail((current) => (current ? { ...current, run: result.run } : current));
      await refreshRecords();
    } finally {
      setActionPending(null);
    }
  }, [refreshRecords, runDetail, runId]);

  const resumeRun = useCallback(async () => {
    if (!runDetail || isTerminalRunStatus(runDetail.run.status)) {
      return;
    }
    setActionPending("resume");
    try {
      const detail = await resumeInterAgentRun(runId, { reason: "chat_graph_resume" });
      setRunDetail(detail);
      await refreshRecords();
    } finally {
      setActionPending(null);
    }
  }, [refreshRecords, runDetail, runId]);

  const stopRun = useCallback(async () => {
    if (!runDetail || isTerminalRunStatus(runDetail.run.status)) {
      return;
    }
    setActionPending("stop");
    try {
      const result = await closeInterAgentRun(runId, { reason: "chat_graph_stop", terminal_status: "cancelled" });
      setRunDetail((current) => (current ? { ...current, run: result.run } : current));
      await refreshRecords();
    } finally {
      setActionPending(null);
    }
  }, [refreshRecords, runDetail, runId]);

  return {
    actionPending,
    approvals,
    artifacts,
    connectionState,
    error,
    events,
    hasMoreHistory,
    isHistoryLoading,
    pauseRun,
    refreshRecords,
    requestOlderHistory,
    resumeRun,
    runDetail,
    stopRun,
  };
}

function applyRunEventUpdates(detail: InterAgentRunDetail | null, events: InterAgentEventRecord[]): InterAgentRunDetail | null {
  if (!detail) {
    return detail;
  }
  let next = detail;
  for (const event of events) {
    if (event.event_type === "inter_agent.participant.status_changed" && event.participant_id) {
      const status = typeof event.payload.status === "string" ? event.payload.status : "";
      if (status) {
        next = {
          ...next,
          participants: next.participants.map((participant) =>
            participant.participant_id === event.participant_id ? { ...participant, status, updated_at: event.created_at } : participant,
          ),
        };
      }
    }
    const runStatus = runStatusFromEvent(event);
    if (runStatus) {
      next = { ...next, run: { ...next.run, status: runStatus, updated_at: event.created_at } };
    }
  }
  return next;
}

function runStatusFromEvent(event: InterAgentEventRecord): InterAgentRunDetail["run"]["status"] | null {
  if (event.event_type === "inter_agent.run.paused") {
    return "paused";
  }
  if (event.event_type === "inter_agent.run.resumed") {
    return "running";
  }
  if (event.event_type === "inter_agent.run.completed") {
    return "completed";
  }
  if (event.event_type === "inter_agent.run.failed") {
    return "failed";
  }
  if (event.event_type === "inter_agent.run.cancelled") {
    return "cancelled";
  }
  return null;
}

function eventsForVisibility(events: InterAgentEventRecord[], visibilityPlane: InterAgentVisibilityPlane): InterAgentEventRecord[] {
  const maximum = visibilityRank(visibilityPlane);
  return events.filter((event) => visibilityRank(event.visibility_plane) <= maximum);
}

function visibilityRank(visibilityPlane: InterAgentVisibilityPlane): number {
  if (visibilityPlane === "debug") {
    return 3;
  }
  if (visibilityPlane === "detail") {
    return 2;
  }
  return 1;
}
