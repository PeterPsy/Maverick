import { useState } from "react";
import { CheckCheck, Clock3, LayoutGrid, Pause, Play, Plus } from "lucide-react";
import { SidebarNav } from "../../components/ui/dashboard-sidebar";
import { useScheduledChats } from "../../hooks/useScheduledChats";
import { notifyShell } from "./chatSidebarStateUtils";
import { ScheduledChatRow } from "../../components/scheduled/ScheduledChatRow";
import "../../styles/scheduled.css";

export function ScheduledSidebar({ mobile }: { mobile: boolean }) {
  const { chats, loading, error, busy, mutate, refresh } = useScheduledChats(null);
  const [filter, setFilter] = useState("all");
  const [query, setQuery] = useState("");
  const views = [
    { id: "all", title: "Scheduled tasks", icon: Clock3 },
    { id: "active", title: "Active tasks", icon: Play },
    { id: "paused", title: "Paused tasks", icon: Pause },
    { id: "completed", title: "Completed tasks", icon: CheckCheck },
  ];
  const visible = chats.filter(task => (filter === "all" || task.status === filter)
    && `${task.title} ${task.instructions}`.toLowerCase().includes(query.trim().toLowerCase()));
  function open(page: string) {
    notifyShell(undefined, { app_page: page });
    if (mobile) window.parent.postMessage({ type: "maverick.shell.sidebar.close" }, "*");
  }
  return <section className="bs-chat-sidebar-block bs-chat-sidebar-block--tasks scheduled-sidebar" aria-label="Scheduled tasks">
    <SidebarNav
      groups={[{ heading: "Scheduled tasks", items: views.map(view => ({ ...view,
        badge: chats.filter(task => view.id === "all" || task.status === view.id).length,
      })) }]}
      activeId={filter}
      onSelect={setFilter}
      viewLabel="Choose task view"
      searchQuery={query}
      onSearchChange={setQuery}
      search={{ label: "Search scheduled tasks", placeholder: "Search scheduled tasks", enableShortcut: false }}
      actions={<>
        <button className="dashboard-sidebar__icon-button" aria-label="Manage scheduled tasks" onClick={() => open("scheduled")} type="button"><LayoutGrid size={15} /></button>
        <button className="dashboard-sidebar__icon-button" aria-label="New scheduled task" onClick={() => open("scheduled/create/new")} type="button"><Plus size={16} /></button>
      </>}
    >
      <div className="scheduled-sidebar__list">
        {error ? <div className="scheduled-sidebar__empty" role="alert"><p>{error}</p><button className="scheduled-text-button" onClick={() => void refresh()} type="button">Retry</button></div>
          : loading ? <p className="scheduled-sidebar__empty" role="status">Loading tasks…</p>
          : visible.length ? visible.map(task => <ScheduledChatRow key={task.id} chat={task} busy={busy} allowDelete={false} onOpen={() => open(`scheduled/${task.id}`)} onAction={(action, item) => {
            void mutate(action, { chat_id: item.id }).then(result => { if (result) void refresh(); });
          }} />)
          : <div className="scheduled-sidebar__empty"><p>{query || filter !== "all" ? "No matching tasks." : "Give your agent a schedule."}</p>{!query && filter === "all" && <button className="scheduled-text-button" onClick={() => open("scheduled/create/new")} type="button">Create a task</button>}</div>}
      </div>
    </SidebarNav>
  </section>;
}
