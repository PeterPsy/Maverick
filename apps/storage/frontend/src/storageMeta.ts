import type { FileRole, PreviewKind } from './types';

export const roleLabels: Record<FileRole, string> = {
  generated: 'Generated',
  uploaded: 'Uploaded'
};

export const kindLabels: Record<PreviewKind, string> = {
  audio: 'Audio',
  document: 'Document',
  file: 'File',
  image: 'Image',
  markdown: 'Markdown',
  pdf: 'PDF',
  presentation: 'Presentation',
  spreadsheet: 'Spreadsheet',
  text: 'Text',
  video: 'Video'
};

export function iconForKind(kind: PreviewKind) {
  return {
    audio: 'audio_file',
    document: 'article',
    file: 'draft',
    image: 'image',
    markdown: 'markdown',
    pdf: 'picture_as_pdf',
    presentation: 'slideshow',
    spreadsheet: 'table',
    text: 'description',
    video: 'movie'
  }[kind];
}

export function formatBytes(value: number) {
  if (value < 1024) return `${value} B`;
  const units = ['KB', 'MB', 'GB'];
  let size = value / 1024;
  for (const unit of units) {
    if (size < 1024) return `${size.toFixed(size >= 10 ? 0 : 1)} ${unit}`;
    size /= 1024;
  }
  return `${size.toFixed(1)} TB`;
}

export function formatMegabytes(value: number) {
  return `${(value / (1024 * 1024)).toFixed(1)} MB`;
}

export type StorageTimestampFormatOptions = {
  fallback?: string;
  locale?: Intl.LocalesArgument;
  timeZone?: string;
};

export function formatStorageTimestamp(value: string | undefined, options: StorageTimestampFormatOptions = {}) {
  const timestamp = value?.trim();
  if (!timestamp) return options.fallback || '';
  const date = new Date(timestamp);
  if (Number.isNaN(date.getTime())) return options.fallback || '';
  return new Intl.DateTimeFormat(options.locale, {
    dateStyle: 'short',
    timeStyle: 'short',
    ...(options.timeZone ? { timeZone: options.timeZone } : {})
  }).format(date);
}
