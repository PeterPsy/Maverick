import type { ChatMessageAttachment } from "../api/client";
import { uploadWorkspaceFile } from "../api/client";
import type { ComposerAttachment } from "./attachments";

export type PendingMessage = {
  clientMessageId: string;
  content: string;
  createdAt: string;
  attachments: ChatMessageAttachment[];
};

export type QueuedMessage = {
  clientMessageId: string;
  content: string;
  attachments: ChatMessageAttachment[];
};

export function attachmentToMessageAttachment(attachment: ComposerAttachment): ChatMessageAttachment {
  return {
    id: attachment.id,
    name: attachment.name,
    size: attachment.size,
    type: attachment.type,
    isImage: attachment.isImage,
    objectUrl: attachment.objectUrl,
    warning: attachment.warning,
  };
}

function fileToBase64(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onerror = () => reject(reader.error || new Error("Unable to read attachment."));
    reader.onload = () => {
      const value = String(reader.result || "");
      resolve(value.includes(",") ? value.split(",", 2)[1] : value);
    };
    reader.readAsDataURL(file);
  });
}

export async function uploadComposerAttachment(attachment: ComposerAttachment): Promise<ChatMessageAttachment> {
  const uploaded = await uploadWorkspaceFile({
    filename: attachment.name,
    content_type: attachment.type,
    content_base64: await fileToBase64(attachment.file),
  });
  return {
    ...attachmentToMessageAttachment(attachment),
    fileId: uploaded.file.file_id,
    relativePath: uploaded.file.relative_path,
  };
}
