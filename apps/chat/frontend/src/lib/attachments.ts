export type ComposerAttachment = {
  id: string;
  file: File;
  name: string;
  size: number;
  type: string;
  objectUrl: string | null;
  isImage: boolean;
  isAudio: boolean;
  warning: string | null;
};

export type ComposerAttachmentOptions = {
  allowedInputModalities?: string[] | null;
};

const MAX_ATTACHMENT_COUNT = 8;
const MAX_ATTACHMENT_SIZE_BYTES = 25 * 1024 * 1024;
const HOSTED_ATTACHMENT_WARNING = "Selected hosted model does not support this attachment type";
const ACCEPTED_MIME_PREFIXES = ["audio/", "image/", "text/"];
const ACCEPTED_MIME_TYPES = new Set([
  "application/json",
  "application/pdf",
  "application/vnd.ms-excel",
  "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
  "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
]);
const ACCEPTED_EXTENSIONS = new Set([".aac", ".csv", ".flac", ".json", ".m4a", ".md", ".mp3", ".oga", ".ogg", ".opus", ".pdf", ".txt", ".wav", ".weba", ".xls", ".xlsx", ".doc", ".docx"]);
const EXTENSION_CONTENT_TYPES = new Map([
  [".aac", "audio/aac"],
  [".flac", "audio/flac"],
  [".m4a", "audio/mp4"],
  [".mp3", "audio/mpeg"],
  [".oga", "audio/ogg"],
  [".ogg", "audio/ogg"],
  [".opus", "audio/ogg"],
  [".wav", "audio/wav"],
  [".weba", "audio/webm"],
]);

function makeAttachmentId(file: File): string {
  return `${file.name}:${file.size}:${file.lastModified}:${crypto.randomUUID()}`;
}

export function formatFileSize(size: number): string {
  if (size < 1024) {
    return `${size} B`;
  }
  if (size < 1024 * 1024) {
    return `${(size / 1024).toFixed(1)} KB`;
  }
  return `${(size / (1024 * 1024)).toFixed(1)} MB`;
}

export function contentTypeForFile(file: File): string {
  const fileName = file.name.toLowerCase();
  const extension = Array.from(EXTENSION_CONTENT_TYPES.keys()).find((item) => fileName.endsWith(item)) || "";
  const normalizedType = file.type.toLowerCase();
  if (extension && (!normalizedType || normalizedType === "application/octet-stream")) {
    return EXTENSION_CONTENT_TYPES.get(extension) || "application/octet-stream";
  }
  if (extension === ".m4a" && ["audio/m4a", "audio/x-m4a", "video/mp4"].includes(normalizedType)) {
    return "audio/mp4";
  }
  return file.type || "application/octet-stream";
}

function attachmentWarning({
  fileName,
  allowedInputModalities = null,
  size,
  type,
}: {
  fileName: string;
  allowedInputModalities?: string[] | null;
  size: number;
  type: string;
}): string | null {
  const isTooLarge = size > MAX_ATTACHMENT_SIZE_BYTES;
  const hasUnsupportedType = !hasAcceptedFileIdentity(fileName, type);
  if (isTooLarge) {
    return `File exceeds the ${formatFileSize(MAX_ATTACHMENT_SIZE_BYTES)} limit`;
  }
  if (hasUnsupportedType) {
    return "Unsupported file type";
  }
  if (allowedInputModalities && !attachmentMatchesInputModalities(type, allowedInputModalities)) {
    return HOSTED_ATTACHMENT_WARNING;
  }
  return null;
}

function hasAcceptedFileIdentity(fileName: string, contentType: string): boolean {
  const mimeType = contentType.toLowerCase();
  const normalizedFileName = fileName.toLowerCase();
  const hasAcceptedMimeType = Boolean(mimeType) && (ACCEPTED_MIME_TYPES.has(mimeType) || ACCEPTED_MIME_PREFIXES.some((prefix) => mimeType.startsWith(prefix)));
  const hasAcceptedExtension = Array.from(ACCEPTED_EXTENSIONS).some((extension) => normalizedFileName.endsWith(extension));
  return hasAcceptedMimeType || hasAcceptedExtension;
}

function attachmentMatchesInputModalities(contentType: string, inputModalities: string[]): boolean {
  const modalities = new Set(inputModalities);
  const modality = attachmentModality(contentType.toLowerCase());
  if (modality === "text") {
    return modalities.has("text") || modalities.has("file") || modalities.has("document");
  }
  if (modality === "pdf") {
    return modalities.has("pdf") || modalities.has("file") || modalities.has("document");
  }
  if (modality === "document") {
    return modalities.has("document") || modalities.has("file");
  }
  if (modality === "spreadsheet") {
    return modalities.has("spreadsheet") || modalities.has("document") || modalities.has("file");
  }
  return modalities.has(modality) || modalities.has("file");
}

function attachmentModality(contentType: string): string {
  if (contentType.startsWith("image/")) {
    return "image";
  }
  if (contentType.startsWith("audio/")) {
    return "audio";
  }
  if (contentType.startsWith("video/")) {
    return "video";
  }
  if (contentType.startsWith("text/") || contentType === "application/json") {
    return "text";
  }
  if (contentType === "application/pdf") {
    return "pdf";
  }
  if (contentType === "application/msword" || contentType === "application/vnd.openxmlformats-officedocument.wordprocessingml.document") {
    return "document";
  }
  if (contentType === "application/vnd.ms-excel" || contentType === "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet") {
    return "spreadsheet";
  }
  return "file";
}

export function buildComposerAttachments(files: File[], existingCount = 0, options: ComposerAttachmentOptions = {}): ComposerAttachment[] {
  const availableSlots = Math.max(0, MAX_ATTACHMENT_COUNT - existingCount);
  return files.slice(0, availableSlots).map((file) => {
    const contentType = contentTypeForFile(file);
    const isImage = contentType.startsWith("image/");
    const isAudio = contentType.startsWith("audio/");
    const name = file.name || "Untitled attachment";
    return {
      id: makeAttachmentId(file),
      file,
      name,
      size: file.size,
      type: contentType,
      objectUrl: isImage ? URL.createObjectURL(file) : null,
      isImage,
      isAudio,
      warning: attachmentWarning({
        fileName: name,
        allowedInputModalities: options.allowedInputModalities,
        size: file.size,
        type: contentType,
      }),
    };
  });
}

export function refreshComposerAttachmentWarnings(
  attachments: ComposerAttachment[],
  options: ComposerAttachmentOptions = {},
): ComposerAttachment[] {
  return attachments.map((attachment) => ({
    ...attachment,
    warning: attachmentWarning({
      fileName: attachment.name,
      allowedInputModalities: options.allowedInputModalities,
      size: attachment.size,
      type: attachment.type,
    }),
  }));
}

export function hasInvalidAttachments(attachments: ComposerAttachment[]): boolean {
  return attachments.some((attachment) => Boolean(attachment.warning));
}

export function canAddMoreAttachments(currentCount: number): boolean {
  return currentCount < MAX_ATTACHMENT_COUNT;
}
