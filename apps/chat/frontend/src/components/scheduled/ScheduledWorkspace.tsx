import { useCallback, useEffect, useRef, useState } from "react";
import { ArrowLeft, Check, Clock3, GripVertical, LayoutGrid, MessageCircle, Pause, Play, Plus, Settings2, Sparkles, Square } from "lucide-react";
import type { ScheduledChat, ScheduledChatSummary, ScheduledConfig, ScheduledStep } from "../../api/scheduledChats";
import { scheduleLabel } from "../../api/scheduledChats";
import type { ChatSurfaceProps } from "../ChatSurface";
import { ChatComposer } from "../ChatComposer";
import { ChatTranscript } from "../ChatTranscript";
import { layoutScheduledGraph } from "../../lib/scheduledGraph";
import { SCHEDULED_CHAT_DRAG_TYPE, scheduledChatDragData, scheduledChatReference, startScheduledChatPointerDrag } from "../../lib/scheduledChatReferences";
import { ScheduledGraph } from "./ScheduledGraph";
import { ScheduledSettings } from "./ScheduledSettings";
import { BlockInspector } from "./BlockInspector";

type Mutate = (action: string, fields?: Record<string, unknown>) => Promise<{ chat?: ScheduledChat; chats?: ScheduledChatSummary[] } | null>;
const EMPTY_STEPS: ScheduledStep[] = [];

export function ScheduledWorkspace({ chat, surface, busy, error, mutate, onBack, refresh }: {
  chat: ScheduledChat; surface: ChatSurfaceProps; busy: boolean; error: string | null; mutate: Mutate; onBack: () => void; refresh: () => Promise<void>;
}) {
  const [draft, setDraft] = useState<ScheduledConfig>(chat);
  const [baseRevision, setBaseRevision] = useState(chat.revision);
  const [dirty, setDirty] = useState(false);
  const [view, setView] = useState<"graph" | "chat">("graph");
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [settings, setSettings] = useState(false);
  const [localError, setLocalError] = useState<string | null>(null);
  const dragCleanup = useRef<(() => void) | null>(null);
  const run = chat.run;
  const locked = Boolean(run && !run.finished_at);
  const running = run?.steps.some(step => step.status === "running") || false;
  const checkpoints = run?.steps.filter(step => step.status === "checkpoint") || [];
  const graph = locked ? chat.graph : draft.graph;
  const block = graph.nodes.find(node => node.id === selectedId);
  const step = run?.steps.find(item => item.node_id === selectedId);
  const stale = chat.revision !== baseRevision && dirty;
  useEffect(() => {
    if (!dirty) { setDraft(chat); setBaseRevision(chat.revision); }
  }, [chat.revision, chat.id, dirty]);
  useEffect(() => () => dragCleanup.current?.(), []);

  const changeGraph = useCallback((graph: ScheduledConfig["graph"]) => { setDraft(current => ({ ...current, graph })); setDirty(true); }, []);
  async function save(config = draft) {
    const result = await mutate("update", { ...config, expected_revision: baseRevision });
    if (!result?.chat) return false;
    setDraft(result.chat); setBaseRevision(result.chat.revision); setDirty(false); setLocalError(null);
    return true;
  }
  const composer = { ...surface.composerProps, disabled: surface.composerProps.disabled || !chat.chat_session_id };
  function askAI() {
    if (dirty) { setLocalError("Save your changes before asking the agent to edit this graph."); return; }
    composer.onReferenceAdd?.(scheduledChatReference(chat));
    composer.onChange(`Create or improve the skill-block graph for this scheduled task. Read its current state with chat_scheduled and save the graph with expected_revision. Keep the blocks focused, use parallel branches where useful, and stop at every checkpoint. Goal: ${chat.instructions}`);
    setView("chat");
  }

  return <section className="scheduled-workspace">
    <header className="scheduled-workspace__header">
      <button className="scheduled-icon-button" aria-label="Back to scheduled tasks" onClick={onBack} type="button"><ArrowLeft size={19} /></button>
      <div className="scheduled-workspace__identity" draggable
        onPointerDown={event => { dragCleanup.current?.(); dragCleanup.current = startScheduledChatPointerDrag(event, chat) || null; }}
        onDragStart={event => { if (dragCleanup.current) { event.preventDefault(); return; } event.dataTransfer.setData(SCHEDULED_CHAT_DRAG_TYPE, scheduledChatDragData(chat)); event.dataTransfer.effectAllowed = "copy"; }}>
        <GripVertical size={14} aria-hidden="true" /><div><h1>{chat.title}</h1><span><Clock3 size={12} />{scheduleLabel(chat.schedule)}</span></div>
      </div>
      <span className={`scheduled-status is-${chat.status}`}>{chat.status}</span>
      <button className="scheduled-icon-button" aria-label={chat.status === "paused" ? "Resume schedule" : "Pause schedule"} disabled={busy} onClick={() => void mutate(chat.status === "paused" ? "resume" : "pause")} type="button">{chat.status === "paused" ? <Play size={17} /> : <Pause size={17} />}</button>
      <button className="scheduled-icon-button" aria-label="Schedule settings" disabled={locked || busy} onClick={() => setSettings(true)} type="button"><Settings2 size={18} /></button>
    </header>
    <div className="scheduled-workspace__toolbar">
      <div className="scheduled-tabs" role="tablist" aria-label="Scheduled task view"><button role="tab" aria-selected={view === "graph"} onClick={() => setView("graph")} type="button"><LayoutGrid size={14} />Blocks</button><button role="tab" aria-selected={view === "chat"} onClick={() => setView("chat")} type="button"><MessageCircle size={14} />Chat</button></div>
      <div className="scheduled-toolbar-actions">
        {!locked && <><button className="scheduled-button is-subtle" disabled={busy || draft.graph.nodes.length >= 64} onClick={() => {
          const id = crypto.randomUUID();
          changeGraph({ ...draft.graph, nodes: [...draft.graph.nodes, { id, title: "New block", instructions: "Describe what the agent should do at this checkpoint.", skill_ids: [], position: { x: 100, y: 150 + draft.graph.nodes.length * 190 } }] });
          setSelectedId(id); setView("graph");
        }} type="button"><Plus size={15} /><span>Add block</span></button>
        <button className="scheduled-icon-button" aria-label="Arrange blocks" disabled={busy} onClick={() => changeGraph(layoutScheduledGraph(draft.graph))} type="button"><LayoutGrid size={16} /></button>
        <button className="scheduled-button is-subtle" disabled={busy || !chat.chat_session_id || dirty} onClick={askAI} type="button"><Sparkles size={15} /><span>Build with AI</span></button></>}
        {dirty && <button className="scheduled-button" disabled={busy || locked} onClick={() => void save()} type="button"><Check size={14} />Save</button>}
        {!locked && <button className="scheduled-button" disabled={busy || dirty || chat.status === "paused"} onClick={() => void mutate("run")} type="button"><Play size={14} /><span>Run now</span></button>}
        {locked && <button className="scheduled-icon-button" aria-label="Cancel current run" disabled={busy} onClick={() => void mutate("cancel")} type="button"><Square size={14} /></button>}
      </div>
    </div>
    {dirty && locked && <div className="scheduled-alert" role="status">This run uses the saved graph. Your edits are kept until it finishes.</div>}
    {(error || localError || stale || chat.message_error) && <div className="scheduled-alert" role="alert">
      <span>{error || localError || (stale ? "The agent changed this graph. Reload to use its latest version, or review your changes before saving." : chat.message_error)}</span>
      {stale && <button className="scheduled-button is-subtle" onClick={() => { setDirty(false); void refresh(); }} type="button">Reload graph</button>}
    </div>}
    {!chat.chat_session_id && <div className="scheduled-alert" role="status"><span>{chat.message_status === "failed" ? "The chat could not start. Check the model in schedule settings." : "Preparing your scheduled task…"}</span>{chat.message_status === "failed" && <button className="scheduled-button is-subtle" disabled={busy} onClick={() => void mutate("initialize")} type="button">Retry chat</button>}</div>}
    {checkpoints.length > 0 && <div className="scheduled-checkpoint"><CircleCheckpoint /><span><strong>{checkpoints.length === 1 ? "Checkpoint ready" : `${checkpoints.length} checkpoints ready`}</strong><small>{running ? "Waiting for the parallel blocks to finish." : "Review the results, then continue to the next blocks."}</small></span><button className="scheduled-button" disabled={busy || running || chat.status === "paused"} onClick={() => void mutate("continue", { run_id: run!.id, node_ids: checkpoints.map(item => item.node_id) })} type="button">Confirm & continue</button></div>}
    <div className="scheduled-workspace__content">
      {view === "graph" ? <><ScheduledGraph graph={graph} schedule={locked ? chat.schedule : draft.schedule} steps={run?.steps || EMPTY_STEPS} selectedId={selectedId} locked={locked || busy} onChange={changeGraph} onSelect={setSelectedId} />
        {block && <BlockInspector key={`${block.id}:${locked ? run!.id : "draft"}`} block={block} step={step} graph={graph} locked={locked} busy={busy} onClose={() => setSelectedId(null)}
          onChange={updated => changeGraph({ ...draft.graph, nodes: draft.graph.nodes.map(node => node.id === updated.id ? updated : node) })}
          onDelete={() => { changeGraph({ nodes: draft.graph.nodes.filter(node => node.id !== block.id), edges: draft.graph.edges.filter(edge => edge.source !== block.id && edge.target !== block.id) }); setSelectedId(null); }}
          onRetry={() => void mutate("retry", { run_id: run!.id, node_id: block.id })} />}</> : <div className="scheduled-conversation"><ChatTranscript {...surface.transcriptProps} composerOverlayHeight={0} /></div>}
    </div>
    <div className="scheduled-workspace__footer"><span>{locked ? `Run ${run!.status}` : `${draft.graph.nodes.length} blocks · ${draft.graph.edges.length} dependencies`}</span>
      {(chat.history?.length || 0) > 0 && <details className="scheduled-history"><summary>Run history</summary><div>{chat.history!.map(item => <p key={item.id}><span>{new Date(item.created_at).toLocaleString("en")}</span><strong>{item.status}</strong></p>)}</div></details>}
      <button className="scheduled-text-button" onClick={() => { composer.onReferenceAdd?.(scheduledChatReference(chat)); composer.onChange(`${composer.value}${composer.value ? " " : ""}@[${chat.title.replace(/[\[\]]/g, "")}](app_ref:chat/scheduled_chat/${chat.id}) `); }} type="button">Add to composer</button>
    </div>
    <div className="scheduled-composer"><ChatComposer {...composer} /></div>
    {settings && <ScheduledSettings initial={draft} busy={busy} error={error} onClose={() => setSettings(false)} onSave={save} />}
  </section>;
}

function CircleCheckpoint() { return <span className="scheduled-checkpoint__icon"><Pause size={17} /></span>; }
