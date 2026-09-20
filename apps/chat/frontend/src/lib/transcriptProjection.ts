import type { ChatMessage, RuntimeEvent } from '../api/client';

export type OrderedMessage = { order: number; sequence: number; message: ChatMessage };
type Group = { events: RuntimeEvent[]; messages: OrderedMessage[] };

// One projection per retained event list, never 80 strong transcript copies.
// Goal updates can amend a message in an earlier turn: those turns share a group.
export class TranscriptProjection {
  private groups = new Map<string, Group>();
  private messages: ChatMessage[] = [];

  project(events: RuntimeEvent[], groupFor: (event: RuntimeEvent) => string,
    projectGroup: (events: RuntimeEvent[]) => OrderedMessage[]): ChatMessage[] {
    const next = new Map<string, RuntimeEvent[]>();
    const positions = new Map<RuntimeEvent, number>();
    events.forEach((event, index) => {
      const key = groupFor(event);
      const group = next.get(key);
      if (group) group.push(event);
      else next.set(key, [event]);
      positions.set(event, index);
    });
    const ordered: OrderedMessage[] = [];
    const groups = new Map<string, Group>();
    for (const [key, incoming] of next) {
      const previous = this.groups.get(key);
      const unchanged = previous && previous.events.length === incoming.length
        && incoming.every((event, index) => equivalentEvent(event, previous.events[index]));
      const projected = unchanged ? previous.messages : projectGroup(incoming);
      if (previous && !unchanged) {
        const byId = new Map(previous.messages.map(({ message }) => [message.id, message]));
        for (const entry of projected) {
          const old = byId.get(entry.message.id);
          if (old && JSON.stringify(old) === JSON.stringify(entry.message)) entry.message = old;
        }
      }
      groups.set(key, { events: incoming, messages: projected });
      for (const entry of projected) ordered.push({ ...entry, order: positions.get(incoming[entry.order])! });
    }
    ordered.sort((a, b) => a.order - b.order || a.sequence - b.sequence);
    const humanIds = new Set<string>();
    const messages: ChatMessage[] = [];
    for (const { message } of ordered) {
      if (message.role === 'human') {
        if (humanIds.has(message.id)) continue;
        humanIds.add(message.id);
      }
      messages.push(message);
    }
    this.groups = groups;
    if (messages.length !== this.messages.length || messages.some((message, index) => message !== this.messages[index])) this.messages = messages;
    return this.messages;
  }
}

export function equivalentEvent(left: RuntimeEvent, right: RuntimeEvent): boolean {
  return left === right || (left.event_id === right.event_id && left.session_id === right.session_id
    && left.turn_id === right.turn_id && left.created_at === right.created_at && left.event_type === right.event_type
    && (left.payload === right.payload || JSON.stringify(left.payload) === JSON.stringify(right.payload)));
}
