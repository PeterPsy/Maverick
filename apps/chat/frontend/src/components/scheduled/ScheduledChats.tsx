import { useEffect, useRef, useState } from "react";
import { Clock3, Plus, Search, Sparkles, X } from "lucide-react";
import { ServerChatApp } from "../../App";
import { newScheduledConfig, type ScheduledChatSummary, type ScheduledConfig } from "../../api/scheduledChats";
import { useScheduledChats } from "../../hooks/useScheduledChats";
import { openAppRouteInShell } from "../../lib/shellNavigation";
import { ScheduledChatRow } from "./ScheduledChatRow";
import { ScheduledSettings } from "./ScheduledSettings";
import { ScheduledWorkspace } from "./ScheduledWorkspace";
import "../../styles/scheduled.css";

export default function ScheduledChats({ chatId, createNew = false, onNavigate }: { chatId: string | null; createNew?: boolean; onNavigate: (page: string) => void }) {
  const state = useScheduledChats(chatId);
  const [query, setQuery] = useState("");
  const [filter, setFilter] = useState("all");
  const [creating, setCreating] = useState<ScheduledConfig | null>(null);
  const [deleting, setDeleting] = useState<ScheduledChatSummary | null>(null);
  const creationId = useRef(crypto.randomUUID());
  const deleteDialog = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    window.parent?.postMessage({ type: "loopino.app.ready", app_id: "chat" }, "*");
  }, []);
  useEffect(() => { if (deleting) deleteDialog.current?.showModal(); }, [deleting]);
  useEffect(() => {
    if (createNew) {
      creationId.current = crypto.randomUUID();
      setCreating(newScheduledConfig("", ""));
    }
  }, [createNew]);
  function navigate(page: string) { onNavigate(page); openAppRouteInShell("chat", page); }
  function newTask(config = newScheduledConfig("", "")) { creationId.current = crypto.randomUUID(); setCreating(config); }
  async function listAction(action: string, chat: ScheduledChatSummary) {
    if (action === "delete") { setDeleting(chat); return; }
    if (await state.mutate(action, { chat_id: chat.id })) await state.refresh();
  }
  if (chatId) {
    if (!state.chat) return <main className="chatapp-root scheduled-loading"><button className="scheduled-text-button" onClick={() => navigate("scheduled")} type="button">Back to scheduled tasks</button><p role={state.error ? "alert" : "status"}>{state.error || "Loading scheduled task…"}</p>{state.error && <button className="scheduled-button" onClick={() => void state.refresh()} type="button">Retry</button>}</main>;
    const chat = state.chat;
    return <ServerChatApp key={chat.id} navigationScope={`scheduled:${chat.id}`} threadId={chat.chat_session_id || null}
      renderSurface={surface => <ScheduledWorkspace chat={chat} surface={surface} busy={state.busy} error={state.error} mutate={state.mutate} onBack={() => navigate("scheduled")} refresh={state.refresh} />} />;
  }
  const visible = state.chats.filter(chat => (filter === "all" || chat.status === filter) && `${chat.title} ${chat.instructions}`.toLowerCase().includes(query.toLowerCase()));
  return <main className="chatapp-root scheduled-root"><div className="scheduled-list">
    <header className="scheduled-list__header"><div><h1>Scheduled tasks</h1><p>Give your agent a rhythm. Build the steps, review the checkpoints.</p></div><button className="scheduled-button" onClick={() => newTask()} type="button"><Plus size={16} />Create</button></header>
    <label className="scheduled-search"><Search size={18} strokeWidth={1.5} /><input aria-label="Search scheduled tasks" placeholder="Search scheduled tasks" value={query} onChange={event => setQuery(event.target.value)} />{query && <button className="scheduled-icon-button" aria-label="Clear search" onClick={() => setQuery("")} type="button"><X size={15} /></button>}</label>
    <div className="scheduled-tabs scheduled-list__tabs" role="tablist" aria-label="Schedule status">{["all", "active", "paused", "completed"].map(status => <button role="tab" aria-selected={filter === status} onClick={() => setFilter(status)} key={status} type="button">{status === "all" ? "All" : status[0].toUpperCase() + status.slice(1)}</button>)}</div>
    {state.error && <div className="scheduled-alert" role="alert"><span>{state.error}</span><button className="scheduled-text-button" onClick={() => void state.refresh()} type="button">Retry</button></div>}
    <section className="scheduled-list__rows" aria-label="Scheduled tasks">
      {state.loading ? <p className="scheduled-muted" role="status">Loading schedules…</p> : visible.length ? visible.map(chat => <ScheduledChatRow key={chat.id} chat={chat} busy={state.busy} onOpen={() => navigate(`scheduled/${chat.id}`)} onAction={(action, item) => void listAction(action, item)} />) : <div className="scheduled-empty"><Clock3 size={30} strokeWidth={1.2} /><h2>{query || filter !== "all" ? "No matching tasks" : "A little structure. More done."}</h2><p>{query || filter !== "all" ? "Try another search or status." : "Schedule a task and give your agent a few clear checkpoints."}</p>{!query && filter === "all" && <button className="scheduled-button is-subtle" onClick={() => newTask()} type="button"><Plus size={15} />Create your first task</button>}</div>}
    </section>
    <section className="scheduled-suggestions"><h2>Start with an idea</h2>{["Daily brief", "Weekly review"].map(title => <button className="scheduled-suggestion" key={title} onClick={() => {
      const goal = title === "Daily brief" ? "Review my calendar and important unread emails. Summarize what needs my attention today." : "Review this week's progress, open tasks and follow-ups. Help me plan the next week.";
      const config = newScheduledConfig(title, goal);
      if (title === "Weekly review") config.schedule = { ...config.schedule, frequency: "weekly", weekday: 4, time: "16:00" };
      newTask(config);
    }} type="button"><Sparkles size={18} strokeWidth={1.5} /><span><strong>{title}</strong><small>{title === "Daily brief" ? "Your day, with the important things first." : "Close the week. Plan what comes next."}</small></span><Plus size={16} /></button>)}</section>
  </div>
    {creating && <ScheduledSettings initial={creating} creating busy={state.busy} error={state.error} onClose={saved => { setCreating(null); if (createNew && !saved) navigate("scheduled"); }} onSave={async config => {
      const result = await state.mutate("create", { ...config, creation_id: creationId.current });
      if (result?.chat) { navigate(`scheduled/${result.chat.id}`); return true; }
      return false;
    }} />}
    {deleting && <dialog className="scheduled-dialog scheduled-delete" ref={deleteDialog} onCancel={() => setDeleting(null)} aria-labelledby="scheduled-delete-title"><h2 id="scheduled-delete-title">Delete “{deleting.title}”?</h2><p>The schedule will be removed and active blocks will stop. Work chats remain in your conversation history.</p>{state.error && <p role="alert" className="scheduled-error">{state.error}</p>}<footer><button className="scheduled-button is-subtle" disabled={state.busy} onClick={() => setDeleting(null)} type="button">Cancel</button><button className="scheduled-button is-danger" disabled={state.busy} onClick={async () => { if (await state.mutate("delete", { chat_id: deleting.id })) { setDeleting(null); await state.refresh(); } }} type="button">Delete schedule</button></footer></dialog>}
  </main>;
}
