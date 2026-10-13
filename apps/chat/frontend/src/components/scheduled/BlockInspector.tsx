import { ExternalLink, Trash2, X } from "lucide-react";
import { useState } from "react";
import type { ScheduledBlock, ScheduledGraph, ScheduledStep } from "../../api/scheduledChats";
import { openChatThreadRouteInShell } from "../../lib/shellNavigation";

export function BlockInspector({ block, step, graph, locked, onChange, onDelete, onClose, onRetry, busy }: {
  block: ScheduledBlock; step?: ScheduledStep; graph: ScheduledGraph; locked: boolean; busy: boolean;
  onChange: (block: ScheduledBlock) => void; onDelete: () => void; onClose: () => void; onRetry: () => void;
}) {
  const [skillsText, setSkillsText] = useState(block.skill_ids.join(", "));
  return <aside className="scheduled-inspector" aria-label="Block details">
    <header><strong>Skill block</strong><button className="scheduled-icon-button" aria-label="Close block details" onClick={onClose} type="button"><X size={17} /></button></header>
    <label>Title<input value={block.title} disabled={locked || busy} maxLength={120} onChange={event => onChange({ ...block, title: event.target.value })} /></label>
    <label>Instructions<textarea aria-label="Instructions" rows={6} value={block.instructions} disabled={locked || busy} maxLength={8000} onChange={event => onChange({ ...block, instructions: event.target.value })} /></label>
    <label>Workspace skill IDs<input value={skillsText} disabled={locked || busy} placeholder="Optional · comma separated" onChange={event => { setSkillsText(event.target.value); onChange({ ...block, skill_ids: event.target.value.split(",").map(id => id.trim()).filter(Boolean) }); }} /></label>
    <p className="scheduled-muted">These instructions and selected skills are injected for this block. The agent stops when the block finishes.</p>
    <div className="scheduled-dependencies"><span>Run after</span><p>{graph.edges.filter(edge => edge.target === block.id).map(edge => graph.nodes.find(node => node.id === edge.source)?.title).join(" + ") || "Schedule trigger"}</p></div>
    {step && <section className="scheduled-inspector__result"><strong>{step.status === "checkpoint" ? "Checkpoint ready" : step.status}</strong>
      {step.output && <pre>{step.output}</pre>}{step.error && <p className="scheduled-error">{step.error}</p>}
      {step.session_id && <button className="scheduled-button is-subtle" onClick={() => openChatThreadRouteInShell(step.session_id)} type="button"><ExternalLink size={14} />Open work chat</button>}
      {(step.status === "failed" || step.status === "cancelled") && locked && <button className="scheduled-button" disabled={busy} onClick={onRetry} type="button">Retry block</button>}
    </section>}
    {!locked && <button className="scheduled-button is-subtle is-danger" disabled={busy || graph.nodes.length === 1} onClick={onDelete} type="button"><Trash2 size={15} />Delete block</button>}
  </aside>;
}
