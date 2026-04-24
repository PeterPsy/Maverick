import { useCallback, useEffect, useMemo, useState } from "react";
import { GraphCanvas } from "./components/GraphCanvas";
import { LeftPanel, RightPanel } from "./components/SidePanels";
import { labelForType } from "./format";
import { callMemory, normalizeViewFilter } from "./memoryApi";
import type { GraphEdge, GraphNode, NodeDetails, ViewFilter } from "./types";

const defaultDraft = { title: "", body: "", type: "note" };

export function MemoryApp() {
  const [nodes, setNodes] = useState<GraphNode[]>([]);
  const [edges, setEdges] = useState<GraphEdge[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [selectedDetails, setSelectedDetails] = useState<NodeDetails | null>(null);
  const [query, setQuery] = useState("");
  const [viewFilter, setViewFilter] = useState<ViewFilter>(() => normalizeViewFilter());
  const [contextText, setContextText] = useState("Run a query to preview the exact context agents will receive.");
  const [draft, setDraft] = useState(defaultDraft);
  const [status, setStatus] = useState("Ready");

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

  const refreshGraph = useCallback(async (override?: { query?: string; viewFilter?: ViewFilter }) => {
    setStatus("Loading graph");
    const effectiveQuery = override?.query ?? query;
    const effectiveViewFilter = override?.viewFilter ?? viewFilter;
    const body: Record<string, unknown> = { action: "graph", query: effectiveQuery, limit: 220 };
    if (effectiveViewFilter.mode === "custom") {
      body.node_ids = effectiveViewFilter.refs.map((ref) => ref.entity_id).filter(Boolean);
    }
    const payload = await callMemory<{ nodes?: GraphNode[]; edges?: GraphEdge[] }>(body);
    hydrateGraph(payload);
    setStatus("Graph updated");
  }, [hydrateGraph, query, viewFilter]);

  const loadViewFilter = useCallback(async () => {
    const payload = await callMemory<{ state?: { view_filter?: ViewFilter } }>({ action: "view_filter" });
    const next = normalizeViewFilter(payload.state?.view_filter);
    setViewFilter(next);
    setQuery(next.query || "");
    return next;
  }, []);

  const selectNode = useCallback(async (id: string | null) => {
    setSelectedId(id);
    if (!id) {
      setSelectedDetails(null);
      return;
    }
    setStatus("Inspecting node");
    const payload = await callMemory<{ node: NodeDetails }>({ action: "inspect", node_id: id });
    setSelectedDetails(payload.node);
    setStatus("Node ready");
  }, []);

  const refreshFromEvents = useCallback(() => {
    loadViewFilter()
      .then((next) => refreshGraph({ query: next.query, viewFilter: next }))
      .catch(() => setStatus("Refresh failed"));
  }, [loadViewFilter, refreshGraph]);

  useEffect(() => {
    refreshFromEvents();
  }, [refreshFromEvents]);

  useEffect(() => {
    window.parent?.postMessage({ type: "maverick.app.ready", app_id: "memory" }, window.location.origin);
  }, []);

  useEffect(() => {
    const onMessage = (event: MessageEvent) => {
      if (event.origin !== window.location.origin || !event.data || typeof event.data !== "object") return;
      if (event.data.type === "maverick.app.data-changed" && event.data.owner_app_id === "memory") refreshFromEvents();
    };
    window.addEventListener("message", onMessage);
    return () => window.removeEventListener("message", onMessage);
  }, [refreshFromEvents]);

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
          if (payload.type === "maverick.app.data-changed" && payload.owner_app_id === "memory") refreshFromEvents();
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
      socket?.close();
    };
  }, [refreshFromEvents]);

  const relationships = useMemo(() => {
    if (!selectedId) return [];
    return edges
      .filter((edge) => edge.source === selectedId || edge.target === selectedId)
      .map((edge) => {
        const otherId = edge.source === selectedId ? edge.target : edge.source;
        return { ...edge, otherId, other: nodeById.get(otherId), direction: edge.source === selectedId ? "Outgoing" : "Incoming" };
      });
  }, [edges, nodeById, selectedId]);

  async function runSearch() {
    const payload = await callMemory<{ state?: { view_filter?: ViewFilter } }>({ action: "set_view_filter", query });
    const next = normalizeViewFilter(payload.state?.view_filter);
    setViewFilter(next);
    await refreshGraph({ query: next.query, viewFilter: next });
  }

  async function remember() {
    const payload = await callMemory<{ node?: GraphNode }>({
      action: "remember",
      title: draft.title,
      body: draft.body,
      type: draft.type,
    });
    setDraft({ ...defaultDraft, type: draft.type });
    await refreshGraph();
    if (payload.node?.id) await selectNode(payload.node.id);
  }

  async function previewContext() {
    const payload = await callMemory<{ items?: Array<{ title: string; summary?: string; body_text?: string; type?: string }> }>({
      action: "context",
      query,
      limit: 8,
    });
    const lines = (payload.items || []).map((item, index) => {
      const body = item.summary || item.body_text || "";
      return `${index + 1}. ${item.title}\n   ${labelForType(item.type || "note")} - ${body}`;
    });
    setContextText(lines.length ? lines.join("\n\n") : "No matching context.");
  }

  async function clearCustomView() {
    const payload = await callMemory<{ state?: { view_filter?: ViewFilter } }>({ action: "clear_custom_view" });
    const next = normalizeViewFilter(payload.state?.view_filter);
    setViewFilter(next);
    setQuery(next.query || "");
    await refreshGraph({ query: next.query, viewFilter: next });
  }

  return (
    <div className="memory-app">
      <LeftPanel
        status={status}
        query={query}
        viewFilter={viewFilter}
        nodeCount={nodes.length}
        edgeCount={edges.length}
        draft={draft}
        onQueryChange={setQuery}
        onSearch={runSearch}
        onClearCustomView={clearCustomView}
        onRefreshGraph={() => refreshGraph()}
        onDraftChange={setDraft}
        onRemember={remember}
      />
      <GraphCanvas
        nodes={nodes}
        edges={edges}
        selectedId={selectedId}
        selectedNode={selectedNode}
        selectedDetails={selectedDetails}
        relationships={relationships}
        setNodes={setNodes}
        onSelectNode={selectNode}
      />
      <RightPanel
        nodes={nodes}
        selectedId={selectedId}
        contextText={contextText}
        onSelectNode={selectNode}
        onPreviewContext={previewContext}
      />
    </div>
  );
}
