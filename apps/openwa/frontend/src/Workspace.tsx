import { useEffect, useState } from "react";
import { connectAppEventSocket, loopinoAppIsVisible } from "@loopino/pwa-cache";
import type { Chat, Session, Status } from "./api";
import { Conversation } from "./Conversation";
import { Icon } from "./Icons";
import { ResourcePanel, SessionSidebar } from "./ResourcePanels";
import { useResources } from "./useResources";

export function Workspace({ status, sessions, selected, online, revision, onSelect, onCreate, onManage }: {
  status: Status; sessions: Session[]; selected: string; online: boolean; revision: number;
  onSelect: (id: string) => void; onCreate: () => void; onManage: () => void;
}) {
  const [chat, setChat] = useState<Chat>();
  const [search, setSearch] = useState("");
  const [tab, setTab] = useState("chats");
  const [page, setPage] = useState(0);
  const session = sessions.find((item) => item.id === selected);
  const resources = useResources(session, tab, page, online, revision);
  useEffect(() => connectAppEventSocket<{ type?: string; owner_app_id?: string; resource?: string }>((event) => {
    if (event.type === "loopino.app.data-changed" && event.owner_app_id === "openwa"
      && event.resource === "messages" && loopinoAppIsVisible()) void resources.refresh();
  }, resources.refresh), [resources.refresh]);
  return <div className={"workspace " + (chat ? "chat-open" : "")}>
    <SessionSidebar sessions={sessions} selected={selected} connection={status.connection} online={online}
      onCreate={onCreate} onSelect={onSelect} />
    <ResourcePanel session={session} tab={tab} chats={resources.chats} chat={chat}
      records={resources.records} search={search} loading={resources.loading} error={resources.error} online={online}
      page={page} more={resources.more} onPage={setPage} onRetry={resources.refresh}
      onManage={onManage} onSearch={setSearch} onChat={setChat}
      onTab={(next) => { setTab(next); setSearch(""); setPage(0); setChat(undefined); }} />
    {session && chat ? <Conversation key={chat.id} sendScope={status.send_scope} session={session} chat={chat}
      online={online} canSend={online && status.connection.role !== "viewer"} onBack={() => setChat(undefined)} />
      : <section className="conversation-placeholder">
        <div className="empty-art"><Icon name="chat" size={40} /></div>
        <h2>{!online ? "Waiting for the gateway" : session?.status === "ready" ? "Choose a conversation" : "Connect your WhatsApp account"}</h2>
        <p>{!online ? "Your sessions will be available when the gateway reconnects." : session?.status === "ready" ? "Select a chat to read messages and reply." : "Link a session to see your conversations here."}</p>
        {online && session && session.status !== "ready" && <button className="primary" onClick={onManage}>
          <Icon name="link" size={18} />Link WhatsApp
        </button>}
      </section>}
  </div>;
}
