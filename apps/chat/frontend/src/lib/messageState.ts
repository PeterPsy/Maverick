import type { AppReference, ChatMessageAttachment, MultiAgentComposerMode, RuntimeTurnClientMetrics } from "../api/client";
import { uploadWorkspaceFile } from "../api/client";
import type { ComposerAttachment } from "./attachments";

export type PendingMessage = {
  clientMessageId: string;
  content: string;
  createdAt: string;
  attachments: ChatMessageAttachment[];
  appReferences: AppReference[];
  invokedSkillIds?: string[];
  multiAgentMode?: MultiAgentComposerMode;
  clientSubmissionStartedAt?: string;
  clientSubmissionMetrics?: RuntimeTurnClientMetrics;
};

export type QueuedMessage = {
  clientMessageId: string;
  content: string;
  attachments: ChatMessageAttachment[];
  appReferences: AppReference[];
  invokedSkillIds?: string[];
  multiAgentMode?: MultiAgentComposerMode;
  clientSubmissionStartedAt?: string;
  clientSubmissionMetrics?: RuntimeTurnClientMetrics;
};

type ComposerAttachmentUploadRecord = {
  startedAt: number;
  completedAt: number | null;
  promise: Promise<ChatMessageAttachment>;
};

const composerAttachmentUploads = new WeakMap<File, ComposerAttachmentUploadRecord>();

export function attachmentToMessageAttachment(attachment: ComposerAttachment): ChatMessageAttachment {
  return {
    id: attachment.id,
    name: attachment.name,
    size: attachment.size,
    type: attachment.type,
    isImage: attachment.isImage,
    isAudio: attachment.isAudio,
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
  const existing = composerAttachmentUploads.get(attachment.file);
  if (existing) {
    return existing.promise;
  }
  const record: ComposerAttachmentUploadRecord = {
    startedAt: performance.now(),
    completedAt: null,
    promise: Promise.resolve({} as ChatMessageAttachment),
  };
  record.promise = fileToBase64(attachment.file)
    .then((contentBase64) =>
      uploadWorkspaceFile({
        filename: attachment.name,
        content_type: attachment.type,
        content_base64: contentBase64,
      }),
    )
    .then((uploaded) => {
      record.completedAt = performance.now();
      return {
        ...attachmentToMessageAttachment(attachment),
        fileId: uploaded.file.file_id,
        relativePath: uploaded.file.relative_path,
      };
    })
    .catch((error) => {
      if (composerAttachmentUploads.get(attachment.file) === record) {
        composerAttachmentUploads.delete(attachment.file);
      }
      throw error;
    });
  composerAttachmentUploads.set(attachment.file, record);
  return record.promise;
}

export function composerAttachmentsUploadSnapshot(attachments: ComposerAttachment[]): {
  readyBeforeSubmit: boolean;
  uploadMs?: number;
} {
  const records = attachments.map((attachment) => composerAttachmentUploads.get(attachment.file));
  const completedRecords = records.filter(
    (record): record is ComposerAttachmentUploadRecord => record !== undefined && record.completedAt !== null,
  );
  if (!attachments.length) {
    return { readyBeforeSubmit: false };
  }
  const snapshot: { readyBeforeSubmit: boolean; uploadMs?: number } = {
    readyBeforeSubmit: completedRecords.length === attachments.length,
  };
  if (completedRecords.length === attachments.length) {
    const startedAt = Math.min(...completedRecords.map((record) => record.startedAt));
    const completedAt = Math.max(...completedRecords.map((record) => record.completedAt as number));
    snapshot.uploadMs = Math.max(0, completedAt - startedAt);
  }
  return snapshot;
}
