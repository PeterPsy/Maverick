import { type DragEvent, useCallback } from "react";
import { filesFromDataTransfer, hasFileDropData } from "../lib/fileDropAttachments";
import { appReferenceMentionItemsFromDataTransfer, hasAppReferenceDragData } from "../lib/storageDragReferences";
import type { MentionItem } from "../lib/mentions";

export function useChatRootDropHandlers({
  disabled,
  handleAddAttachments,
  handleAddReferenceMentions,
}: {
  disabled: boolean;
  handleAddAttachments: (files: File[]) => void;
  handleAddReferenceMentions: (items: MentionItem[]) => void;
}) {
  const handleChatRootDragOver = useCallback(
    (event: DragEvent<HTMLElement>) => {
      if (disabled || (!hasFileDropData(event.dataTransfer) && !hasAppReferenceDragData(event.dataTransfer))) {
        return;
      }
      event.preventDefault();
      event.stopPropagation();
      event.dataTransfer.dropEffect = "copy";
    },
    [disabled],
  );
  const handleChatRootDrop = useCallback(
    (event: DragEvent<HTMLElement>) => {
      if (disabled) {
        return;
      }
      if (hasAppReferenceDragData(event.dataTransfer)) {
        const items = appReferenceMentionItemsFromDataTransfer(event.dataTransfer);
        if (!items.length) return;
        event.preventDefault();
        event.stopPropagation();
        handleAddReferenceMentions(items);
        return;
      }
      const files = filesFromDataTransfer(event.dataTransfer);
      if (!files.length) {
        return;
      }
      event.preventDefault();
      event.stopPropagation();
      handleAddAttachments(files);
    },
    [disabled, handleAddAttachments, handleAddReferenceMentions],
  );

  return { handleChatRootDragOver, handleChatRootDrop };
}
