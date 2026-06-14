import type { ChatMessage, ChatProject, ChatThread, RuntimeEvent } from "../../api/client";
import { eventsToMessages } from "../../lib/transcript";
import type { FolderSection } from "./sections";

const SEARCH_RESULTS_SECTION_ID = "search-results";

export type TranscriptSearchTextByThreadId = Record<string, string>;

export function buildSearchSections({
  emptyLabel = "No chats found.",
  projects,
  query,
  threads,
  transcriptTextByThreadId,
}: {
  emptyLabel?: string;
  projects: ChatProject[];
  query: string;
  threads: ChatThread[];
  transcriptTextByThreadId?: TranscriptSearchTextByThreadId;
}): FolderSection[] {
  const projectNames = projectNameById(projects);
  const results = searchChatThreads({
    projectNames,
    query,
    threads,
    transcriptTextByThreadId: transcriptTextByThreadId || {},
  });
  return [
    {
      id: SEARCH_RESULTS_SECTION_ID,
      projectId: null,
      title: "Search results",
      canManage: false,
      canCreateProject: false,
      canMoveThreads: false,
      emptyLabel,
      items: results.map((result) => result.thread),
    },
  ];
}

export type ChatThreadSearchResult = {
  thread: ChatThread;
  score: number;
  lastMessageAt: number;
};

export function searchChatThreads({
  projectNames,
  query,
  threads,
  transcriptTextByThreadId,
}: {
  projectNames: Map<string, string>;
  query: string;
  threads: ChatThread[];
  transcriptTextByThreadId: TranscriptSearchTextByThreadId;
}): ChatThreadSearchResult[] {
  const parsed = parseSearchQuery(query);
  if (!parsed.tokens.length) {
    return threads.map((thread) => ({
      thread,
      score: 0,
      lastMessageAt: threadLastMessageTimestamp(thread),
    }));
  }

  return threads
    .map((thread) => {
      const projectName = thread.project_id ? projectNames.get(thread.project_id) || "" : "";
      const searchable = {
        title: normalizedSearchText(thread.title),
        project: normalizedSearchText(projectName),
        transcript: normalizedSearchText(transcriptTextByThreadId[thread.thread_id] || ""),
        metadata: normalizedSearchText(
          [
            thread.thread_id,
            thread.runtime_session_id,
            thread.agent_label,
            thread.agent_type_id,
            thread.agent_role_id,
            thread.source_app_id,
            thread.system_prompt,
          ].join(" "),
        ),
      };
      const score = scoreThreadMatch(searchable, parsed);
      if (score <= 0) {
        return null;
      }
      return {
        thread,
        score,
        lastMessageAt: threadLastMessageTimestamp(thread),
      };
    })
    .filter((item): item is ChatThreadSearchResult => Boolean(item))
    .sort((left, right) => {
      if (left.score !== right.score) {
        return right.score - left.score;
      }
      if (left.lastMessageAt !== right.lastMessageAt) {
        return right.lastMessageAt - left.lastMessageAt;
      }
      return left.thread.thread_id.localeCompare(right.thread.thread_id);
    });
}

export function transcriptSearchTextFromEvents(events: RuntimeEvent[]): string {
  const messages = eventsToMessages(events);
  return messages.map(messageSearchText).filter(Boolean).join(" ");
}

export function threadSearchCacheKey(thread: ChatThread): string {
  return [
    thread.runtime_session_id,
    threadLastMessageTimestamp(thread),
    thread.updated_at || "",
    thread.last_completed_turn_id || "",
  ].join(":");
}

export function threadLastMessageTimestamp(thread: ChatThread): number {
  return Math.max(
    timestampValue(thread.last_user_message_at),
    timestampValue(thread.last_completed_response_at),
    timestampValue(thread.updated_at),
    timestampValue(thread.created_at),
  );
}

function projectNameById(projects: ChatProject[]): Map<string, string> {
  return new Map(projects.map((project) => [project.project_id, project.name]));
}

function messageSearchText(message: ChatMessage): string {
  if (message.role === "tool" || message.role === "step") {
    return "";
  }
  const referenceText = (message.appReferences || [])
    .map((reference) => {
      if (reference.type === "entity") {
        return [reference.app_id, reference.entity_type, reference.entity_id, reference.label, reference.summary].filter(Boolean).join(" ");
      }
      return [reference.app_id, reference.label].filter(Boolean).join(" ");
    })
    .join(" ");
  return [message.content, referenceText].filter(Boolean).join(" ");
}

function parseSearchQuery(query: string): { phrase: string; tokens: string[] } {
  const phrase = normalizedSearchText(query);
  const tokens = Array.from(new Set(phrase.split(/\s+/).filter(Boolean)));
  return { phrase, tokens };
}

function scoreThreadMatch(
  searchable: { title: string; project: string; transcript: string; metadata: string },
  parsed: { phrase: string; tokens: string[] },
): number {
  const haystack = [searchable.title, searchable.project, searchable.transcript, searchable.metadata].join(" ");
  if (!parsed.tokens.every((token) => haystack.includes(token))) {
    return 0;
  }

  let score = 1;
  score += scoreField(searchable.title, parsed, 700, 460, 260);
  score += scoreField(searchable.project, parsed, 280, 180, 120);
  score += scoreField(searchable.transcript, parsed, 220, 150, 95);
  score += scoreField(searchable.metadata, parsed, 70, 45, 25);
  return score;
}

function scoreField(field: string, parsed: { phrase: string; tokens: string[] }, exactScore: number, startsScore: number, tokenScore: number): number {
  if (!field) {
    return 0;
  }
  if (field === parsed.phrase) {
    return exactScore;
  }
  if (field.startsWith(parsed.phrase)) {
    return startsScore;
  }
  if (field.includes(parsed.phrase)) {
    return Math.round(startsScore * 0.78);
  }
  if (parsed.tokens.every((token) => field.includes(token))) {
    return tokenScore;
  }
  return parsed.tokens.some((token) => field.includes(token)) ? Math.round(tokenScore * 0.35) : 0;
}

function normalizedSearchText(value: string): string {
  return value
    .normalize("NFKD")
    .replace(/[\u0300-\u036f]/g, "")
    .toLowerCase()
    .replace(/[^\p{L}\p{N}]+/gu, " ")
    .trim();
}

function timestampValue(value: string | null | undefined): number {
  if (!value) {
    return 0;
  }
  const parsed = Date.parse(value);
  return Number.isFinite(parsed) ? parsed : 0;
}
