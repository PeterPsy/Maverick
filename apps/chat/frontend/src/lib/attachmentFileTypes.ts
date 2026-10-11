const ACCEPTED_MIME_PREFIXES = ["audio/", "image/", "text/"];
const ACCEPTED_MIME_TYPES = new Set([
  "application/json",
  "application/pdf",
  "application/vnd.ms-excel",
  "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
  "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
  "application/zip",
  "application/x-zip-compressed",
  "application/vnd.rar",
  "application/x-rar",
  "application/x-rar-compressed",
  "application/x-7z-compressed",
  "application/x-tar",
  "application/gzip",
  "application/x-gzip",
  "application/x-bzip",
  "application/x-bzip2",
  "application/x-xz",
  "application/x-lzip",
  "application/x-lzma",
  "application/x-lzop",
  "application/x-lz4",
  "application/zstd",
  "application/x-zstd",
  "application/x-compress",
  "application/vnd.ms-cab-compressed",
  "application/x-cpio",
  "application/x-archive",
  "application/x-arj",
  "application/x-ace-compressed",
  "application/x-lzh-compressed",
  "application/x-stuffit",
  "application/x-stuffitx",
]);
const ACCEPTED_EXTENSIONS = new Set([
  ".aac", ".csv", ".flac", ".json", ".m4a", ".md", ".mp3", ".oga", ".ogg", ".opus", ".pdf", ".txt", ".wav", ".weba", ".xls", ".xlsx", ".doc", ".docx",
  ".zip", ".zipx", ".rar", ".7z", ".tar", ".gz", ".gzip", ".tgz",
  ".bz", ".bz2", ".bzip", ".bzip2", ".tbz", ".tbz2", ".xz", ".txz",
  ".lz", ".lzip", ".lzma", ".tlz", ".lzo", ".lz4", ".z", ".taz",
  ".zst", ".zstd", ".tzst", ".br", ".cab", ".arj", ".ace", ".arc",
  ".lzh", ".lha", ".sit", ".sitx", ".cpio", ".xar", ".zpaq", ".paq", ".pea", ".alz",
]);

export const COMPOSER_ATTACHMENT_ACCEPT = [
  ...ACCEPTED_MIME_PREFIXES.map((prefix) => `${prefix}*`),
  ...ACCEPTED_MIME_TYPES,
  ...ACCEPTED_EXTENSIONS,
].join(",");

export function hasAcceptedFileIdentity(fileName: string, contentType: string): boolean {
  const mimeType = contentType.toLowerCase();
  const normalizedFileName = fileName.toLowerCase();
  const hasAcceptedMimeType = Boolean(mimeType) && (ACCEPTED_MIME_TYPES.has(mimeType) || ACCEPTED_MIME_PREFIXES.some((prefix) => mimeType.startsWith(prefix)));
  const hasAcceptedExtension = Array.from(ACCEPTED_EXTENSIONS).some((extension) => normalizedFileName.endsWith(extension));
  return hasAcceptedMimeType || hasAcceptedExtension;
}
