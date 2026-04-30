export type MentionKind = "app" | "skill";

export type MentionTrigger = "@" | "$";

export type MentionItem = {
  id: string;
  label: string;
  description: string;
  kind: MentionKind;
};

export type ActiveMention = {
  kind: MentionKind;
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

export type MentionAppReference = {
  type: "app";
  app_id: string;
  label?: string;
};

const TRIGGER_KIND: Record<MentionTrigger, MentionKind> = {
  "@": "app",
  "$": "skill",
};

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
    ? items.filter((item) => `${item.label} ${item.id} ${item.description}`.toLowerCase().includes(normalizedQuery))
    : items;
  return filtered.slice(0, limit);
}

export function applyMention(text: string, mention: ActiveMention, item: MentionItem): { value: string; cursor: number } {
  const replacement = `${mention.trigger}${item.label} `;
  const nextValue = `${text.slice(0, mention.start)}${replacement}${text.slice(mention.end)}`;
  return {
    value: nextValue,
    cursor: mention.start + replacement.length,
  };
}

export function mentionText(item: MentionItem): string {
  return `${item.kind === "app" ? "@" : "$"}${item.label}`;
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
    if (token.item.kind !== "app") {
      continue;
    }
    referencesById.set(token.item.id, {
      type: "app",
      app_id: token.item.id,
      label: token.item.label,
    });
  }
  return [...referencesById.values()];
}

export function removeMentionToken(text: string, token: MentionToken): { value: string; cursor: number } {
  const removeEnd = token.end < text.length && text[token.end] === " " ? token.end + 1 : token.end;
  const value = `${text.slice(0, token.start)}${text.slice(removeEnd)}`.replace(/ {2,}/g, " ");
  return {
    value,
    cursor: token.start,
  };
}
