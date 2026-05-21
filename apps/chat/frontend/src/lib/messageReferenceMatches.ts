import type { AppReference } from "../api/client";
import { referenceKey } from "./mentions";
import type { MentionItem } from "./mentions";

export type MessageMentionMatch = {
  kind: MentionItem["kind"];
  id: string;
  label: string;
  start: number;
  end: number;
  appId?: string;
  deepLink?: string;
  entityType?: string;
  exists?: boolean;
  summary?: string;
};

export function fallbackMatchesForAppReference(content: string, reference: AppReference): MessageMentionMatch[] {
  if (reference.type === "entity") {
    const label = reference.label?.trim() || reference.entity_id;
    const marker = `[ref:${reference.app_id}/${reference.entity_type}/${reference.entity_id}]`;
    const markerMatches = fallbackEntityReferenceCandidates(content, marker);
    const labelMatches = markerMatches.length ? [] : fallbackReferenceCandidates(content, [`@${label}`]);
    return [...markerMatches, ...labelMatches].map((match) => ({
      ...match,
      kind: "entity" as const,
      id: referenceKey(reference),
      appId: reference.app_id,
      entityType: reference.entity_type,
      label,
      deepLink: reference.deep_link,
      exists: reference.exists,
      summary: reference.summary,
    }));
  }
  const label = reference.label?.trim();
  const candidates = [`@${reference.app_id}`, label ? `@${label}` : ""].filter(Boolean);
  return fallbackReferenceCandidates(content, candidates).map((match) => ({
    ...match,
    kind: "app" as const,
    id: reference.app_id,
    label: reference.label || reference.app_id,
  }));
}

function fallbackEntityReferenceCandidates(content: string, marker: string): Pick<MessageMentionMatch, "start" | "end">[] {
  const matches: Pick<MessageMentionMatch, "start" | "end">[] = [];
  let searchFrom = 0;
  while (searchFrom < content.length) {
    const markerStart = content.indexOf(marker, searchFrom);
    if (markerStart < 0) {
      break;
    }
    const mentionStart = entityReferenceMentionStart(content, markerStart);
    matches.push({
      start: mentionStart ?? markerStart,
      end: markerStart + marker.length,
    });
    searchFrom = markerStart + marker.length;
  }
  return matches;
}

function entityReferenceMentionStart(content: string, markerStart: number): number | null {
  if (markerStart <= 0 || !/[ \t]/.test(content[markerStart - 1])) {
    return null;
  }
  let labelEnd = markerStart;
  while (labelEnd > 0 && /[ \t]/.test(content[labelEnd - 1])) {
    labelEnd -= 1;
  }
  const separator = content.slice(labelEnd, markerStart);
  if (!separator || !/^[ \t]+$/.test(separator)) {
    return null;
  }
  const atIndex = content.lastIndexOf("@", labelEnd - 1);
  if (atIndex < 0) {
    return null;
  }
  if (atIndex > 0 && !/\s/.test(content[atIndex - 1])) {
    return null;
  }
  const label = content.slice(atIndex + 1, labelEnd).trim();
  if (!label || /[\r\n\[\]]/.test(label)) {
    return null;
  }
  return atIndex;
}

function fallbackReferenceCandidates(content: string, candidates: string[]): Pick<MessageMentionMatch, "start" | "end">[] {
  return candidates
    .filter(Boolean)
    .map((candidate) => {
      const start = content.indexOf(candidate);
      return start >= 0 ? { start, end: start + candidate.length } : null;
    })
    .filter((match): match is Pick<MessageMentionMatch, "start" | "end"> => Boolean(match));
}

export function rangesOverlap(left: Pick<MessageMentionMatch, "start" | "end">, right: Pick<MessageMentionMatch, "start" | "end">): boolean {
  return left.start < right.end && right.start < left.end;
}
