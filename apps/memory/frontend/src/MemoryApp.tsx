import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { CreateNodeModal } from "./components/CreateNodeModal";
import { GraphCanvas } from "./components/GraphCanvas";
import { notifyActiveMemorySelection } from "./lib/activeMemorySelection";
import { nodeIdFromParams, scalarString, shouldOpenCreateNode } from "./lib/memoryNavigationParams";
import { callMemory, normalizeViewFilter } from "./memoryApi";
import type { GraphEdge, GraphNode, NodeDetails, NodeDraft, ViewFilter } from "./types";

const defaultDraft = { title: "", body: "", type: "note" };

export function MemoryApp() {
  const eventRefreshTimerRef = useRef<number | null>(null);
  const [nodes, setNodes] = useState<GraphNode[]>([]);
  const [edges, setEdges] = useState<GraphEdge[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [selectedDetails, setSelectedDetails] = useState<NodeDetails | null>(null);
  const [query, setQuery] = useState("");
  const [viewFilter, setViewFilter] = useState<ViewFilter>(() => normalizeViewFilter());
  const [draft, setDraft] = useState<NodeDraft>(defaultDraft);
  const [status, setStatus] = useState("Ready");
  const [createModalOpen, setCreateModalOpen] = useState(false);
  const [creatingNode, setCreatingNode] = useState(false);
  const [error, setError] = useState("");
  const consumedCreateRequests = useRef<Set<string>>(new Set());
  const consumedLegacyCreateRequest = useRef(false);
  const selectedIdRef = useRef<string | null>(null);

  const nodeById = useMemo(() => new Map(nodes.map((node) => [node.id, node])), [nodes]);
  const selectedNode = selectedId ? nodeById.get(selectedId) || null : null;

  const hydrateGraph = useCallback((payload: { nodes?: GraphNode[]; edges?: GraphEdge[] }) => {
    const center = { x: 450, y: 310 };
    setNodes((current) => {
      const existing = new Map(current.map((node) => [node.id, node]));
      const incoming = payload.nodes || [];
      return incoming.map((node, index) => {
        const previous = existing.get(node.id);
        const angle = (index / Math.max(1, incoming.length)) * Math.PI * 2;
        const radius = 110 + Math.min(280, incoming.length * 10);
        return {
          ...node,
          x: previous?.x ?? center.x + Math.cos(angle) * radius,
          y: previous?.y ?? center.y + Math.sin(angle) * radius,
          vx: previous?.vx ?? 0,
          vy: previous?.vy ?? 0,
          radius: 13 + Math.min(13, Number(node.importance || 0.5) * 15),
        };
      });
    });
    setEdges(payload.edges || []);
  }, []);

  const refreshGraph = useCallback(async (override: { query: string; viewFilter: ViewFilter }) => {
    setStatus("Loading graph");
    const effectiveQuery = override.query;
    const effectiveViewFilter = override.viewFilter;
    const body: Record<string, unknown> = { action: "graph", query: effectiveQuery, limit: 220 };
    if (effectiveViewFilter.mode === "custom") {
      body.node_ids = effectiveViewFilter.refs.map((ref) => ref.entity_id).filter(Boolean);
    }
    const payload = await callMemory<{ nodes?: GraphNode[]; edges?: GraphEdge[] }>(body);
    hydrateGraph(payload);
    setStatus("Graph updated");
  }, [hydrateGraph]);

  const loadViewFilter = useCallback(async () => {
    const payload = await callMemory<{ state?: { view_filter?: ViewFilter } }>({ action: "view_filter" });
    const next = normalizeViewFilter(payload.state?.view_filter);
    setViewFilter(next);
    setQuery(next.query || "");
    return next;
  }, []);

  const selectNode = useCallback(async (id: string | null) => {
    setSelectedId(id);
    selectedIdRef.current = id;
    if (!id) {
      setSelectedDetails(null);
      return;
    }
    notifyActiveMemorySelection(id);
    setStatus("Inspecting node");
    const payload = await callMemory<{ node: NodeDetails }>({ action: "inspect", node_id: id });
    setSelectedDetails(payload.node);
    setStatus("Node ready");
  }, []);

  const refreshMemory = useCallback(() => {
    loadViewFilter()
      .then((next) => refreshGraph({ query: next.query, viewFilter: next }))
      .catch(() => setStatus("Refresh failed"));
  }, [loadViewFilter, refreshGraph]);

  useEffect(() => {
    refreshMemory();
  }, [refreshMemory]);

  const scheduleEventRefresh = useCallback(() => {
    if (eventRefreshTimerRef.current !== null) window.clearTimeout(eventRefreshTimerRef.current);
    eventRefreshTimerRef.current = window.setTimeout(() => {
      eventRefreshTimerRef.current = null;
      refreshMemory();
    }, 250);
  }, [refreshMemory]);

  useEffect(() => {
    return () => {
      if (eventRefreshTimerRef.current !== null) window.clearTimeout(eventRefreshTimerRef.current);
    };
  }, []);

  useEffect(() => {
    window.parent?.postMessage({ type: "maverick.app.ready", app_id: "memory" }, window.location.origin);
  }, []);

  useEffect(() => {
    const onMessage = (event: MessageEvent) => {
      if (event.origin !== window.location.origin || !event.data || typeof event.data !== "object") return;
      const payload = event.data as {
        app_id?: string;
        owner_app_id?: string;
        params?: Record<string, string | boolean | null>;
        resource?: string;
        type?: string;
      };
      if (payload.type === "maverick.app.navigate" && (!payload.app_id || payload.app_id === "memory")) {
        void handleNavigationParams(payload.params || {});
        return;
      }
      if (payload.type === "maverick.app.data-changed" && payload.owner_app_id === "memory") scheduleEventRefresh();
    };
    window.addEventListener("message", onMessage);
    return () => window.removeEventListener("message", onMessage);
  }, [nodes, scheduleEventRefresh]);

  useEffect(() => {
    if (!("WebSocket" in window)) return undefined;
    let closed = false;
    let retry = 0;
    let reconnectTimer: number | null = null;
    let socket: WebSocket | null = null;
    const connect = () => {
      const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
      socket = new WebSocket(`${protocol}//${window.location.host}/api/apps/events/ws`);
      socket.onopen = () => {
        retry = 0;
      };
      socket.onmessage = (event) => {
        try {
          const payload = JSON.parse(event.data);
          if (payload.type === "maverick.app.data-changed" && payload.owner_app_id === "memory") scheduleEventRefresh();
        } catch {
          // Ignore malformed event frames.
        }
      };
      socket.onerror = () => socket?.close();
      socket.onclose = () => {
        if (closed) return;
        const delay = Math.min(5000, 500 + retry * 750);
        retry += 1;
        reconnectTimer = window.setTimeout(connect, delay);
      };
    };
    connect();
    return () => {
      closed = true;
      if (reconnectTimer !== null) window.clearTimeout(reconnectTimer);
      if (eventRefreshTimerRef.current !== null) window.clearTimeout(eventRefreshTimerRef.current);
      socket?.close();
    };
  }, [scheduleEventRefresh]);

  const relationships = useMemo(() => {
    if (!selectedId) return [];
    return edges
      .filter((edge) => edge.source === selectedId || edge.target === selectedId)
      .map((edge) => {
        const otherId = edge.source === selectedId ? edge.target : edge.source;
        return { ...edge, otherId, other: nodeById.get(otherId), direction: edge.source === selectedId ? "Outgoing" : "Incoming" };
      });
  }, [edges, nodeById, selectedId]);

  async function remember() {
    setCreatingNode(true);
    setError("");
    try {
      const payload = await callMemory<{ node?: GraphNode }>({
        action: "remember",
        title: draft.title,
        body: draft.body,
        type: draft.type,
      });
      setDraft({ ...defaultDraft, type: draft.type });
      setCreateModalOpen(false);
      await refreshGraph({ query, viewFilter });
      if (payload.node?.id) await selectNode(payload.node.id);
    } catch (createError) {
      setError(createError instanceof Error ? createError.message : "Unable to create node.");
    } finally {
      setCreatingNode(false);
    }
  }

  async function handleNavigationParams(params: Record<string, string | boolean | null>) {
    const requestedNodeId = nodeIdFromParams(params);
    if (requestedNodeId) {
      if (nodes.some((node) => node.id === requestedNodeId) || selectedIdRef.current !== requestedNodeId) {
        await selectNode(requestedNodeId);
      }
    }
    if (!shouldOpenCreateNode(params)) {
      return;
    }
    const requestId = scalarString(params.new_node_request_id);
    if (requestId) {
      if (consumedCreateRequests.current.has(requestId)) {
        return;
      }
      consumedCreateRequests.current.add(requestId);
    } else if (consumedLegacyCreateRequest.current) {
      return;
    } else {
      consumedLegacyCreateRequest.current = true;
    }
    setCreateModalOpen(true);
  }

  return (
    <main className="memory-shell">
      {error ? <div className="memory-error">{error}</div> : null}
      <GraphCanvas
        nodes={nodes}
        edges={edges}
        selectedId={selectedId}
        selectedNode={selectedNode}
        selectedDetails={selectedDetails}
        relationships={relationships}
        status={status}
        setNodes={setNodes}
        onRefreshGraph={() => refreshGraph({ query, viewFilter })}
        onSelectNode={selectNode}
      />
      <CreateNodeModal
        draft={draft}
        open={createModalOpen}
        saving={creatingNode}
        onClose={() => {
          if (!creatingNode) setCreateModalOpen(false);
        }}
        onCreate={remember}
        onDraftChange={setDraft}
      />
    </main>
  );
}
