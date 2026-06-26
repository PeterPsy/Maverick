import { useEffect, useRef, useState } from "react";
import { buildComposerAttachments, ComposerAttachment, type ComposerAttachmentOptions, refreshComposerAttachmentWarnings } from "../lib/attachments";

export function useComposerAttachments(options: ComposerAttachmentOptions = {}) {
  const [attachments, setAttachments] = useState<ComposerAttachment[]>([]);
  const objectUrlsRef = useRef<Set<string>>(new Set());

  function addAttachments(files: File[]) {
    setAttachments((current) => {
      const nextAttachments = buildComposerAttachments(files, current.length, options);
      nextAttachments.forEach((attachment) => {
        if (attachment.objectUrl) {
          objectUrlsRef.current.add(attachment.objectUrl);
        }
      });
      return [...current, ...nextAttachments];
    });
  }

  function clearAttachments() {
    setAttachments([]);
  }

  function removeAttachment(attachmentId: string) {
    setAttachments((current) => {
      const next = current.filter((attachment) => attachment.id !== attachmentId);
      const removed = current.find((attachment) => attachment.id === attachmentId);
      if (removed?.objectUrl) {
        URL.revokeObjectURL(removed.objectUrl);
        objectUrlsRef.current.delete(removed.objectUrl);
      }
      return next;
    });
  }

  useEffect(() => {
    return () => {
      objectUrlsRef.current.forEach((objectUrl) => URL.revokeObjectURL(objectUrl));
      objectUrlsRef.current.clear();
    };
  }, []);

  useEffect(() => {
    setAttachments((current) => refreshComposerAttachmentWarnings(current, options));
  }, [options.inputMode]);

  return {
    addAttachments,
    attachments,
    clearAttachments,
    removeAttachment,
  };
}
