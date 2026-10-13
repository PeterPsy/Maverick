import { Clock3 } from "lucide-react";
import { useScheduledChats } from "../../hooks/useScheduledChats";
import { openAppRouteInShell } from "../../lib/shellNavigation";
import { ScheduledChatRow } from "../../components/scheduled/ScheduledChatRow";
import "../../styles/scheduled.css";

export function ScheduledSidebar({ mobile }: { mobile: boolean }) {
  const { chats, busy, mutate, refresh } = useScheduledChats(null);
  function open(page: string) {
    openAppRouteInShell("chat", page);
    if (mobile) window.parent.postMessage({ type: "maverick.shell.sidebar.close" }, "*");
  }
  return <section className="scheduled-sidebar" aria-label="Scheduled chats">
    <div className="scheduled-sidebar__heading"><button onClick={() => open("scheduled")} type="button"><Clock3 size={15} />Scheduled chats</button></div>
    {chats.slice(0, 4).map(chat => <ScheduledChatRow key={chat.id} chat={chat} busy={busy} allowDelete={false} onOpen={() => open(`scheduled/${chat.id}`)} onAction={(action, item) => {
      void mutate(action, { chat_id: item.id }).then(result => { if (result) void refresh(); });
    }} />)}
  </section>;
}
