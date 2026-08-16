import type { AppReference } from "../api/client";

export type MentionKind = "app" | "entity" | "skill";

export type MentionTrigger = "@" | "$";
export type MentionTriggerKind = "app" | "skill";

export type MentionItem = {
  id: string;
  label: string;
  description: string;
  kind: MentionKind;
  reference?: AppReference;
};

export type ActiveMention = {
  kind: MentionTriggerKind;
  trigger: MentionTrigger;
  start: number;
  end: number;
  query: string;
};

export type MentionToken = {
  item: MentionItem;
  start: number;
  end: number;
  text: string;
};

export type MentionAppReference = AppReference;

export type EntityReferenceMarker = {
  appId: string;
  entityType: string;
  entityId: string;
  label: string;
  markerStart: number;
  markerEnd: number;
  mentionStart: number | null;
};

const TRIGGER_KIND: Record<MentionTrigger, MentionTriggerKind> = {
  "@": "app",
  "$": "skill",
};
const ENTITY_REFERENCE_MARKER_PATTERN = /\[ref:([^/\]\s]+)\/([^/\]\s]+)\/([^\]\s]+)\]/g;

function isMentionTrigger(value: string): value is MentionTrigger {
  return value === "@" || value === "$";
}

function canStartMention(text: string, index: number): boolean {
  if (index === 0) {
    return true;
  }
  return /\s/.test(text[index - 1]);
}

export function activeMentionAt(text: string, cursor: number): ActiveMention | null {
  const boundedCursor = Math.max(0, Math.min(cursor, text.length));
  for (let index = boundedCursor - 1; index >= 0; index -= 1) {
    const char = text[index];
    if (char === "\n") {
      return null;
    }
    if (!isMentionTrigger(char)) {
      continue;
    }
    if (!canStartMention(text, index)) {
      return null;
    }
    return {
      kind: TRIGGER_KIND[char],
      trigger: char,
      start: index,
      end: boundedCursor,
      query: text.slice(index + 1, boundedCursor),
    };
  }
  return null;
}

export function filterMentionItems(items: MentionItem[], query: string, limit = 8): MentionItem[] {
  const normalizedQuery = query.trim().toLowerCase();
  const filtered = normalizedQuery
    ? items.filter((item) => mentionItemMatchesQuery(item, normalizedQuery))
    : items;
  return filtered.slice(0, limit);
}

function mentionItemMatchesQuery(item: MentionItem, normalizedQuery: string): boolean {
  const haystack = `${item.label} ${item.id} ${item.description} ${referenceSearchText(item.reference)}`.toLowerCase();
  if (haystack.includes(normalizedQuery)) {
    return true;
  }
  return normalizedQuery
    .split(/\s+/)
    .filter(Boolean)
    .every((token) => tokenVariants(token).some((variant) => haystack.includes(variant)));
}

function tokenVariants(token: string): string[] {
  if (token.length > 4 && token.endsWith("s")) {
    return [token, token.slice(0, -1)];
  }
  return [token];
}

function referenceSearchText(reference: AppReference | undefined): string {
  if (!reference || reference.type !== "entity") {
    return "";
  }
  return [reference.app_id, reference.entity_type, reference.entity_id, reference.summary, reference.deep_link].filter(Boolean).join(" ");
}

export function applyMention(text: string, mention: ActiveMention, item: MentionItem): { value: string; cursor: number } {
  const replacement = `${mentionText(item)} `;
  const nextValue = `${text.slice(0, mention.start)}${replacement}${text.slice(mention.end)}`;
  return {
    value: nextValue,
    cursor: mention.start + replacement.length,
  };
}

export function mentionText(item: MentionItem): string {
  if (item.kind === "skill") {
    return `$${item.id}`;
  }
  if (item.reference?.type === "entity") {
    return `@${item.label} [ref:${item.reference.app_id}/${item.reference.entity_type}/${item.reference.entity_id}]`;
  }
  return `@${item.label}`;
}

function canEndMention(text: string, index: number): boolean {
  if (index >= text.length) {
    return true;
  }
  return /\s|[.,;:!?)]/.test(text[index]);
}

function findAllTokenMatches(text: string, item: MentionItem): MentionToken[] {
  const target = mentionText(item);
  const matches: MentionToken[] = [];
  let searchFrom = 0;
  while (searchFrom < text.length) {
    const start = text.indexOf(target, searchFrom);
    if (start === -1) {
      break;
    }
    const end = start + target.length;
    if (canStartMention(text, start) && canEndMention(text, end)) {
      matches.push({ item, start, end, text: target });
    }
    searchFrom = start + 1;
  }
  return matches;
}

export function findMentionTokens(text: string, items: MentionItem[]): MentionToken[] {
  const matches = items.flatMap((item) => findAllTokenMatches(text, item));
  return matches
    .sort((first, second) => first.start - second.start || second.end - first.end)
    .filter((match, index, sorted) => index === 0 || match.start >= sorted[index - 1].end);
}

export function appReferencesFromText(text: string, items: MentionItem[]): MentionAppReference[] {
  const referencesById = new Map<string, MentionAppReference>();
  for (const token of findMentionTokens(text, items)) {
    if (token.item.kind !== "app" && token.item.kind !== "entity") {
      continue;
    }
    const reference = token.item.reference || {
      type: "app" as const,
      app_id: token.item.id,
      label: token.item.label,
    };
    referencesById.set(referenceKey(reference), reference);
  }
  for (const marker of findEntityReferenceMarkers(text)) {
    const reference: MentionAppReference = {
      type: "entity",
      app_id: marker.appId,
      entity_type: marker.entityType,
      entity_id: marker.entityId,
      label: marker.label || marker.entityId,
    };
    const key = referenceKey(reference);
    if (!referencesById.has(key)) {
      referencesById.set(key, reference);
    }
  }
  return [...referencesById.values()];
}

export function skillIdsFromText(text: string, items: MentionItem[]): string[] {
  const skillIds = new Set<string>();
  for (const token of findMentionTokens(text, items)) {
    if (token.item.kind === "skill") {
      skillIds.add(token.item.id);
    }
  }
  return [...skillIds];
}

export function findEntityReferenceMarkers(text: string): EntityReferenceMarker[] {
  return [...text.matchAll(ENTITY_REFERENCE_MARKER_PATTERN)].map((match) => {
    const markerStart = match.index || 0;
    const markerEnd = markerStart + match[0].length;
    const mention = entityReferenceMentionPrefix(text, markerStart);
    return {
      appId: match[1],
      entityType: match[2],
      entityId: match[3],
      label: mention?.label || match[3],
      markerStart,
      markerEnd,
      mentionStart: mention?.start ?? null,
    };
  });
}

function entityReferenceMentionPrefix(text: string, markerStart: number): { start: number; label: string } | null {
  if (markerStart <= 0 || !/[ \t]/.test(text[markerStart - 1])) {
    return null;
  }
  let labelEnd = markerStart;
  while (labelEnd > 0 && /[ \t]/.test(text[labelEnd - 1])) {
    labelEnd -= 1;
  }
  const separator = text.slice(labelEnd, markerStart);
  if (!separator || !/^[ \t]+$/.test(separator)) {
    return null;
  }
  const atIndex = text.lastIndexOf("@", labelEnd - 1);
  if (atIndex < 0 || !canStartMention(text, atIndex)) {
    return null;
  }
  const label = text.slice(atIndex + 1, labelEnd).trim();
  if (!label || /[\r\n\[\]]/.test(label)) {
    return null;
  }
  return { start: atIndex, label };
}

export function referenceKey(reference: AppReference): string {
  if (reference.type === "entity") {
    return `${reference.type}:${reference.app_id}:${reference.entity_type}:${reference.entity_id}`;
  }
  return `${reference.type}:${reference.app_id}`;
}

export function removeMentionToken(text: string, token: MentionToken): { value: string; cursor: number } {
  const removeEnd = token.end < text.length && text[token.end] === " " ? token.end + 1 : token.end;
  const value = `${text.slice(0, token.start)}${text.slice(removeEnd)}`.replace(/ {2,}/g, " ");
  return {
    value,
    cursor: token.start,
  };
}
