import { type DragEvent, useCallback } from "react";
import { filesFromDataTransfer, hasFileDropData } from "../lib/fileDropAttachments";

export function useChatRootDropHandlers({
  disabled,
  handleAddAttachments,
}: {
  disabled: boolean;
  handleAddAttachments: (files: File[]) => void;
}) {
  const handleChatRootDragOver = useCallback(
    (event: DragEvent<HTMLElement>) => {
      if (disabled || !hasFileDropData(event.dataTransfer)) {
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
      const files = filesFromDataTransfer(event.dataTransfer);
      if (!files.length) {
        return;
      }
      event.preventDefault();
      event.stopPropagation();
      handleAddAttachments(files);
    },
    [disabled, handleAddAttachments],
  );

  return { handleChatRootDragOver, handleChatRootDrop };
}
