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

const MAX_ATTACHMENT_COUNT = 8;
const MAX_ATTACHMENT_SIZE_BYTES = 25 * 1024 * 1024;
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

function hasAcceptedType(file: File): boolean {
  const mimeType = contentTypeForFile(file).toLowerCase();
  const fileName = file.name.toLowerCase();
  const hasAcceptedMimeType = Boolean(mimeType) && (ACCEPTED_MIME_TYPES.has(mimeType) || ACCEPTED_MIME_PREFIXES.some((prefix) => mimeType.startsWith(prefix)));
  const hasAcceptedExtension = Array.from(ACCEPTED_EXTENSIONS).some((extension) => fileName.endsWith(extension));
  return hasAcceptedMimeType || hasAcceptedExtension;
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

export function buildComposerAttachments(files: File[], existingCount = 0): ComposerAttachment[] {
  const availableSlots = Math.max(0, MAX_ATTACHMENT_COUNT - existingCount);
  return files.slice(0, availableSlots).map((file) => {
    const contentType = contentTypeForFile(file);
    const isImage = contentType.startsWith("image/");
    const isAudio = contentType.startsWith("audio/");
    const isTooLarge = file.size > MAX_ATTACHMENT_SIZE_BYTES;
    const hasUnsupportedType = !hasAcceptedType(file);
    return {
      id: makeAttachmentId(file),
      file,
      name: file.name || "Untitled attachment",
      size: file.size,
      type: contentType,
      objectUrl: isImage ? URL.createObjectURL(file) : null,
      isImage,
      isAudio,
      warning: isTooLarge
        ? `File exceeds the ${formatFileSize(MAX_ATTACHMENT_SIZE_BYTES)} limit`
        : hasUnsupportedType
          ? "Unsupported file type"
          : null,
    };
  });
}

export function hasInvalidAttachments(attachments: ComposerAttachment[]): boolean {
  return attachments.some((attachment) => Boolean(attachment.warning));
}

export function canAddMoreAttachments(currentCount: number): boolean {
  return currentCount < MAX_ATTACHMENT_COUNT;
}
