import type { AppReference } from "../api/client";
import type { MentionItem, MentionKind } from "./mentions";

type ReferenceKindLabelInput = {
  appId?: string;
  entityType?: string;
  kind: MentionKind;
  reference?: AppReference;
  summary?: string;
};

const STORAGE_FILE_KIND_LABELS: Record<string, string> = {
  audio: "Audio",
  document: "Document",
  file: "File",
  image: "Image",
  markdown: "Markdown",
  pdf: "PDF",
  presentation: "Slides",
  spreadsheet: "Sheet",
  text: "Text",
  video: "Video",
};

export function mentionItemKindLabel(item: MentionItem): string {
  return referenceKindLabel({ kind: item.kind, reference: item.reference });
}

export function referenceKindLabel(input: ReferenceKindLabelInput): string {
  if (input.kind === "app") {
    return "App";
  }
  if (input.kind === "skill") {
    return "Skill";
  }
  const reference = input.reference?.type === "entity" ? input.reference : null;
  return entityReferenceKindLabel({
    appId: reference?.app_id || input.appId,
    entityType: reference?.entity_type || input.entityType,
    summary: reference?.summary || input.summary,
  });
}

function entityReferenceKindLabel({
  appId,
  entityType,
  summary,
}: {
  appId?: string;
  entityType?: string;
  summary?: string;
}): string {
  if (appId === "storage") {
    if (entityType === "folder") {
      return "Folder";
    }
    if (entityType === "file") {
      return storageFileKindLabel(summary);
    }
  }
  return "Record";
}

function storageFileKindLabel(summary?: string): string {
  const previewKind = String(summary || "")
    .trim()
    .toLowerCase()
    .match(/^([a-z]+)\s+file\b/)?.[1];
  return (previewKind && STORAGE_FILE_KIND_LABELS[previewKind]) || "File";
}
