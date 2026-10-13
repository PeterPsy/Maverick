import { memo, useCallback, useMemo, useState } from "react";
import { Background, BackgroundVariant, Controls, Handle, MarkerType, Position, ReactFlow, applyNodeChanges,
  type Node, type NodeProps, type NodeChange, type Connection, type Edge } from "@xyflow/react";
import { Check, CirclePause, Clock3, GitBranch, LoaderCircle, Repeat2 } from "lucide-react";
import "@xyflow/react/dist/style.css";
import { scheduleLabel, type ChatSchedule, type ScheduledGraph as Graph, type ScheduledStep } from "../../api/scheduledChats";
import { canConnectBlocks } from "../../lib/scheduledGraph";

type BlockNode = Node<{ title: string; instructions: string; status: string; skills: number; kind?: string }, "skill">;
const SkillNode = memo(function SkillNode({ data, selected }: NodeProps<BlockNode>) {
  const Icon = data.kind === "schedule" ? Clock3 : data.kind === "loop" ? Repeat2 : data.status === "completed" ? Check : data.status === "running" ? LoaderCircle : data.status === "checkpoint" ? CirclePause : GitBranch;
  return <div className={`scheduled-node ${selected ? "is-selected" : ""} is-${data.status} ${data.kind ? `is-${data.kind}` : ""}`}>
    {data.kind !== "schedule" && <Handle type="target" position={Position.Left} isConnectable={!data.kind} />}
    <div className="scheduled-node__heading"><Icon size={17} strokeWidth={1.6} className={data.status === "running" ? "scheduled-spin" : ""} /><strong>{data.title}</strong></div>
    <p>{data.instructions}</p>
    {!data.kind && <footer><span>{data.status === "pending" ? "Skill block" : data.status === "checkpoint" ? "Checkpoint · confirm to continue" : data.status}</span>{data.skills > 0 && <span>{data.skills} skill{data.skills > 1 ? "s" : ""}</span>}</footer>}
    {data.kind !== "loop" && <Handle type="source" position={Position.Right} isConnectable={!data.kind} />}
  </div>;
});
const nodeTypes = { skill: SkillNode };
const edgeOptions = { type: "smoothstep", markerEnd: { type: MarkerType.ArrowClosed, width: 15, height: 15 }, style: { strokeWidth: 1.4 } };
function geometry(height: number, kind?: "schedule" | "loop") {
  return { initialWidth: 250, initialHeight: height, handles: [
    ...(kind !== "loop" ? [{ type: "source" as const, position: Position.Right, x: 245.5, y: height / 2 - 4.5, width: 9, height: 9 }] : []),
    ...(kind !== "schedule" ? [{ type: "target" as const, position: Position.Left, x: -4.5, y: height / 2 - 4.5, width: 9, height: 9 }] : []),
  ] };
}
const blockGeometry = geometry(170);
const scheduleGeometry = geometry(128, "schedule");
const loopGeometry = geometry(128, "loop");

export function ScheduledGraph({ graph, schedule, steps, locked, selectedId, onChange, onSelect }: {
  graph: Graph; schedule: ChatSchedule; steps: ScheduledStep[]; locked: boolean;
  selectedId: string | null;
  onChange: (graph: Graph) => void; onSelect: (nodeId: string | null) => void;
}) {
  const [dragPositions, setDragPositions] = useState<Record<string, { x: number; y: number }>>({});
  const nodes = useMemo<BlockNode[]>(() => {
    const blockNodes = graph.nodes.map(node => ({ id: node.id, type: "skill" as const, ...blockGeometry, position: dragPositions[node.id] || node.position,
      selected: selectedId === node.id, data: { title: node.title, instructions: node.instructions, status: steps.find(step => step.node_id === node.id)?.status || "pending", skills: node.skill_ids.length } }));
    const minX = Math.min(...graph.nodes.map(node => node.position.x));
    const maxX = Math.max(...graph.nodes.map(node => node.position.x));
    return [
      { id: "__schedule", type: "skill", ...scheduleGeometry, position: { x: minX - 320, y: 150 }, draggable: false, selectable: false, data: { kind: "schedule", title: "Schedule", instructions: scheduleLabel(schedule), status: "pending", skills: 0 } },
      ...blockNodes,
      { id: "__loop", type: "skill", ...loopGeometry, position: { x: maxX + 340, y: 150 }, draggable: false, selectable: false, data: { kind: "loop", title: schedule.frequency === "manual" || schedule.frequency === "once" ? "Finish" : "Chat loop", instructions: schedule.frequency === "manual" || schedule.frequency === "once" ? "Complete after all checkpoints." : "Wait for the next scheduled run.", status: "pending", skills: 0 } },
    ];
  }, [graph.nodes, schedule, steps, selectedId, dragPositions]);
  const edges = useMemo<Edge[]>(() => [
    ...graph.edges.map(edge => ({ ...edge, ...edgeOptions, selectable: !locked, deletable: !locked })),
    ...graph.nodes.filter(node => !graph.edges.some(edge => edge.target === node.id)).map(node => ({ id: `__start-${node.id}`, source: "__schedule", target: node.id, ...edgeOptions, selectable: false, deletable: false, className: "scheduled-edge-guide" })),
    ...graph.nodes.filter(node => !graph.edges.some(edge => edge.source === node.id)).map(node => ({ id: `__end-${node.id}`, source: node.id, target: "__loop", ...edgeOptions, selectable: false, deletable: false, className: "scheduled-edge-guide" })),
  ], [graph, locked]);
  const connect = useCallback((connection: Connection) => {
    if (!locked && canConnectBlocks(graph, connection.source, connection.target)) onChange({ ...graph, edges: [...graph.edges, { id: crypto.randomUUID(), source: connection.source, target: connection.target }] });
  }, [graph, locked, onChange]);
  const valid = useCallback((connection: Connection | Edge) => !locked && canConnectBlocks(graph, connection.source, connection.target), [graph, locked]);
  const changeNodes = useCallback((changes: NodeChange<BlockNode>[]) => {
    const selection = changes.find(change => change.type === "select" && change.selected);
    if (selection && selection.type === "select") onSelect(selection.id);
    if (locked) return;
    const positions = changes.filter(change => change.type === "position");
    if (!positions.length) return;
    const changed = applyNodeChanges(positions, nodes);
    setDragPositions(Object.fromEntries(changed.filter(node => !node.id.startsWith("__")).map(node => [node.id, node.position])));
    if (positions.some(change => change.type === "position" && change.dragging === false)) {
      onChange({ ...graph, nodes: graph.nodes.map(block => ({ ...block, position: changed.find(node => node.id === block.id)?.position || block.position })) });
      setDragPositions({});
    }
  }, [graph, locked, nodes, onChange, onSelect]);
  return <div className="scheduled-canvas" aria-label="Scheduled chat skill graph">
    <ReactFlow nodes={nodes} edges={edges} nodeTypes={nodeTypes} onNodesChange={changeNodes} onConnect={connect}
      isValidConnection={valid} nodesDraggable={!locked} nodesConnectable={!locked} deleteKeyCode={null}
      onEdgesDelete={deleted => { if (!locked) onChange({ ...graph, edges: graph.edges.filter(edge => !deleted.some(item => item.id === edge.id)) }); }}
      onEdgeDoubleClick={(_, edge) => { if (!locked && !edge.id.startsWith("__")) onChange({ ...graph, edges: graph.edges.filter(item => item.id !== edge.id) }); }}
      onNodeClick={(_, node) => { if (!node.id.startsWith("__")) onSelect(node.id); }}
      onPaneClick={() => onSelect(null)} fitView fitViewOptions={{ padding: 0.15, maxZoom: 0.95,
        nodes: window.innerWidth <= 680 ? graph.nodes.slice(0, 1).map(node => ({ id: node.id })) : undefined }}
      minZoom={0.15} maxZoom={1.6} defaultEdgeOptions={edgeOptions} proOptions={{ hideAttribution: true }}>
      <Background variant={BackgroundVariant.Dots} gap={24} size={1} /><Controls showInteractive={false} />
    </ReactFlow>
    <p className="scheduled-canvas__hint">{locked ? "Confirm checkpoints to move the loop forward." : "Connect blocks to set dependencies. Double-click a connection to remove it."}</p>
  </div>;
}
