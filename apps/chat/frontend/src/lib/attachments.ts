export type ComposerAttachment = {
  id: string;
  file: File;
  name: string;
  size: number;
  type: string;
  objectUrl: string | null;
  isImage: boolean;
  warning: string | null;
};

const MAX_ATTACHMENT_COUNT = 8;
const MAX_ATTACHMENT_SIZE_BYTES = 25 * 1024 * 1024;
const ACCEPTED_MIME_PREFIXES = ["image/", "text/"];
const ACCEPTED_MIME_TYPES = new Set([
  "application/json",
  "application/pdf",
  "application/vnd.ms-excel",
  "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
  "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
]);
const ACCEPTED_EXTENSIONS = new Set([".csv", ".json", ".md", ".pdf", ".txt", ".xls", ".xlsx", ".doc", ".docx"]);

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
  const mimeType = file.type.toLowerCase();
  const fileName = file.name.toLowerCase();
  const hasAcceptedMimeType = Boolean(mimeType) && (ACCEPTED_MIME_TYPES.has(mimeType) || ACCEPTED_MIME_PREFIXES.some((prefix) => mimeType.startsWith(prefix)));
  const hasAcceptedExtension = Array.from(ACCEPTED_EXTENSIONS).some((extension) => fileName.endsWith(extension));
  return hasAcceptedMimeType || hasAcceptedExtension;
}

export function buildComposerAttachments(files: File[], existingCount = 0): ComposerAttachment[] {
  const availableSlots = Math.max(0, MAX_ATTACHMENT_COUNT - existingCount);
  return files.slice(0, availableSlots).map((file) => {
    const isImage = file.type.startsWith("image/");
    const isTooLarge = file.size > MAX_ATTACHMENT_SIZE_BYTES;
    const hasUnsupportedType = !hasAcceptedType(file);
    return {
      id: makeAttachmentId(file),
      file,
      name: file.name || "Untitled attachment",
      size: file.size,
      type: file.type || "application/octet-stream",
      objectUrl: isImage ? URL.createObjectURL(file) : null,
      isImage,
      warning: isTooLarge
        ? `File oltre il limite di ${formatFileSize(MAX_ATTACHMENT_SIZE_BYTES)}`
        : hasUnsupportedType
          ? "Tipo file non supportato"
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
