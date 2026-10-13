import { useEffect, useRef, useState } from "react";
import * as Menu from "@radix-ui/react-dropdown-menu";
import { Clock3, Ellipsis, Pause, Play, Trash2 } from "lucide-react";
import { scheduleLabel, type ScheduledChatSummary } from "../../api/scheduledChats";
import { SCHEDULED_CHAT_DRAG_TYPE, scheduledChatDragData, startScheduledChatPointerDrag } from "../../lib/scheduledChatReferences";

export function ScheduledChatRow({ chat, busy, onOpen, onAction, allowDelete = true }: {
  chat: ScheduledChatSummary; busy: boolean; onOpen: () => void; onAction: (action: string, chat: ScheduledChatSummary) => void; allowDelete?: boolean;
}) {
  const dragCleanup = useRef<(() => void) | null>(null);
  const [dragging, setDragging] = useState(false);
  useEffect(() => () => dragCleanup.current?.(), []);
  return <article className={`scheduled-row ${dragging ? "is-dragging" : ""}`} draggable
    onPointerDown={event => { dragCleanup.current?.(); dragCleanup.current = startScheduledChatPointerDrag(event, chat, setDragging) || null; }}
    onDragStart={event => {
      if (dragCleanup.current) { event.preventDefault(); return; }
      event.dataTransfer.setData(SCHEDULED_CHAT_DRAG_TYPE, scheduledChatDragData(chat)); event.dataTransfer.effectAllowed = "copy";
    }}>
    <Clock3 aria-hidden="true" className={`scheduled-status-icon is-${chat.status}`} size={19} strokeWidth={1.5} />
    <button className="scheduled-row__open" data-scheduled-drag-open onClick={onOpen} type="button">
      <span className="scheduled-row__title">{chat.title}</span>
      <span className="scheduled-muted">{scheduleLabel(chat.schedule)}</span>
      <span className="scheduled-row__next">{chat.run_status === "checkpoint" ? "Waiting at checkpoint" : chat.status === "paused" ? "Paused" : chat.status === "completed" ? "Completed" : chat.next_run_at ? `Next ${new Date(chat.next_run_at).toLocaleString("en", { dateStyle: "medium", timeStyle: "short" })}` : "Ready to run"}</span>
    </button>
    <Menu.Root><Menu.Trigger asChild><button className="scheduled-icon-button" aria-label={`Actions for ${chat.title}`} disabled={busy} type="button"><Ellipsis size={18} /></button></Menu.Trigger>
      <Menu.Portal><Menu.Content className="scheduled-menu" sideOffset={6} align="end" collisionPadding={12}>
        <Menu.Item onSelect={() => onAction("run", chat)} disabled={chat.status !== "active"}><Play size={15} />Run now</Menu.Item>
        <Menu.Item onSelect={() => onAction(chat.status === "paused" ? "resume" : "pause", chat)}><Pause size={15} />{chat.status === "paused" ? "Resume" : "Pause"}</Menu.Item>
        {allowDelete && <><Menu.Separator /><Menu.Item className="is-danger" onSelect={() => onAction("delete", chat)}><Trash2 size={15} />Delete</Menu.Item></>}
      </Menu.Content></Menu.Portal>
    </Menu.Root>
  </article>;
}
