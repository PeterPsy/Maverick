import { referenceKey } from "../lib/mentions";
import type { MentionItem } from "../lib/mentions";

function mentionItemKey(item: MentionItem): string {
  return item.reference ? referenceKey(item.reference) : `${item.kind}:${item.id}`;
}

export function mergeMentionItems(...groups: MentionItem[][]): MentionItem[] {
  const seen = new Set<string>();
  const merged: MentionItem[] = [];
  for (const group of groups) {
    for (const item of group) {
      const key = mentionItemKey(item);
      if (seen.has(key)) {
        continue;
      }
      seen.add(key);
      merged.push(item);
    }
  }
  return merged;
}
