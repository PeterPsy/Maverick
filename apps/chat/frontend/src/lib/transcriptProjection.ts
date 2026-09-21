import type { ChatMessage, RuntimeEvent } from '../api/client';

export type OrderedMessage = { order: number; sequence: number; message: ChatMessage };
type Group = { events: RuntimeEvent[]; messages: OrderedMessage[]; ordered: OrderedMessage[] };
type ProjectGroup = (events: RuntimeEvent[]) => OrderedMessage[];

// One bounded projection per retained event window. Goal amendments can regroup
// earlier turns; their explicit signature selects the full reconciliation path.
export class TranscriptProjection {
  private groups = new Map<string, Group>();
  private messages: ChatMessage[] = [];
  private events: RuntimeEvent[] = [];
  private positions = new Map<RuntimeEvent, number>();
  private firstPosition = 0;
  private groupingSignature = '';

  project(events: RuntimeEvent[], groupFor: (event: RuntimeEvent) => string,
    projectGroup: ProjectGroup, groupingSignature: string): ChatMessage[] {
    const position = events.length ? this.positions.get(events[0]) : undefined;
    const start = position === undefined ? -1 : position - this.firstPosition;
    const overlap = this.events.length - start;
    const extendsWindow = start >= 0 && overlap > 0 && overlap <= events.length
      && groupingSignature === this.groupingSignature
      && events.every((event, index) => index >= overlap || event === this.events[start + index]);
    if (extendsWindow) {
      const changed = new Map<string, RuntimeEvent[]>();
      for (let index = 0; index < start; index++) {
        const removed = this.events[index];
        this.positions.delete(removed);
        changed.set(groupFor(removed), []);
      }
      for (const key of changed.keys()) {
        changed.set(key, this.groups.get(key)!.events.filter(event => this.positions.has(event)));
      }
      this.firstPosition = position!;
      for (let index = overlap; index < events.length; index++) {
        const event = events[index];
        const key = groupFor(event);
        let incoming = changed.get(key);
        if (!incoming) {
          incoming = this.groups.get(key)?.events.slice() ?? [];
          changed.set(key, incoming);
        }
        incoming.push(event);
        this.positions.set(event, this.firstPosition + index);
      }
      for (const [key, incoming] of changed) {
        if (incoming.length) this.groups.set(key, this.projectGroup(incoming, this.groups.get(key), projectGroup));
        else this.groups.delete(key);
      }
      this.events = events;
      if (!changed.size) return this.messages;
    } else {
      const incoming = new Map<string, RuntimeEvent[]>();
      this.positions = new Map();
      this.firstPosition = 0;
      events.forEach((event, index) => {
        const key = groupFor(event);
        const group = incoming.get(key);
        if (group) group.push(event);
        else incoming.set(key, [event]);
        this.positions.set(event, index);
      });
      const previous = this.groups;
      this.groups = new Map();
      for (const [key, group] of incoming) this.groups.set(key, this.projectGroup(group, previous.get(key), projectGroup));
      this.events = events;
      this.groupingSignature = groupingSignature;
    }
    const ordered: OrderedMessage[] = [];
    for (const group of this.groups.values()) for (const entry of group.ordered) ordered.push(entry);
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
    if (messages.length !== this.messages.length || messages.some((message, index) => message !== this.messages[index])) this.messages = messages;
    return this.messages;
  }

  private projectGroup(incoming: RuntimeEvent[], previous: Group | undefined, project: ProjectGroup): Group {
    const unchanged = previous && previous.events.length === incoming.length
      && incoming.every((event, index) => equivalentEvent(event, previous.events[index]));
    const messages = unchanged ? previous.messages : project(incoming);
    if (previous && !unchanged) {
      const byId = new Map(previous.messages.map(({ message }) => [message.id, message]));
      for (const entry of messages) {
        const old = byId.get(entry.message.id);
        if (old && JSON.stringify(old) === JSON.stringify(entry.message)) entry.message = old;
      }
    }
    const ordered = messages.map(entry => ({ ...entry, order: this.positions.get(incoming[entry.order])! }));
    return { events: incoming, messages, ordered };
  }
}

export function equivalentEvent(left: RuntimeEvent, right: RuntimeEvent): boolean {
  return left === right || (left.event_id === right.event_id && left.session_id === right.session_id
    && left.turn_id === right.turn_id && left.created_at === right.created_at && left.event_type === right.event_type
    && (left.payload === right.payload || JSON.stringify(left.payload) === JSON.stringify(right.payload)));
}
