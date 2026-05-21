import type { DragEvent } from "react";
import { BusyChatGlow } from "../BusyChatGlow";
import type { FloatingChatWindow } from "./floatingState";

export function FloatingLauncher({
  isActiveThreadBusy,
  isActiveThreadUnread,
  onDragOver,
  onDrop,
  onOpen,
  windowItem,
}: {
  isActiveThreadBusy: boolean;
  isActiveThreadUnread: boolean;
  onDragOver: (event: DragEvent<HTMLElement>) => void;
  onDrop: (event: DragEvent<HTMLElement>) => void;
  onOpen: () => void;
  windowItem: FloatingChatWindow;
}) {
  return (
    <button
      aria-busy={isActiveThreadBusy || undefined}
      aria-label={isActiveThreadBusy ? "Open active chat" : isActiveThreadUnread ? "Open chat with unread response" : "Open chat"}
      className={`chat-floating-widget-launcher ${windowItem.isCollapsed ? "" : "is-hidden"} ${isActiveThreadBusy ? "is-busy" : ""} ${
        isActiveThreadUnread ? "is-unread" : ""
      }`}
      onClick={onOpen}
      onDragOver={onDragOver}
      onDrop={onDrop}
      type="button"
    >
      {isActiveThreadBusy ? <BusyChatGlow /> : null}
      <span aria-hidden="true" className="material-symbols-rounded">
        forum
      </span>
    </button>
  );
}
