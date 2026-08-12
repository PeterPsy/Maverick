import { ChatProject, ChatThread } from "../../api/client";
import { isOpenDesignSourceApp, sourceAppPresentation } from "../../lib/sourceAppPresentation";
import { threadLastMessageTimestamp } from "./threadTimestamps";

export const HOT_THREAD_WINDOW_MS = 24 * 60 * 60 * 1000;

export type FolderSection = {
  id: string;
  projectId: string | null;
  title: string;
  items: ChatThread[];
  canManage: boolean;
  canCreateProject: boolean;
  canMoveThreads: boolean;
  emptyLabel: string;
};

export type ThreadFilter = "all" | "hot" | "unread" | "opendesign" | "senses" | "multi_agent";

export type ThreadSourceBadge = {
  icon: string;
  kind: "multi_agent" | "opendesign" | "senses" | "source_app";
  label: string;
};

function sectionLatestActivity(section: FolderSection): number {
  return section.items.reduce((latest, thread) => Math.max(latest, threadLastMessageTimestamp(thread)), 0);
}

function compareProjectSections(left: FolderSection, right: FolderSection): number {
  const activityDifference = sectionLatestActivity(right) - sectionLatestActivity(left);
  if (activityDifference !== 0) {
    return activityDifference;
  }
  const titleDifference = left.title.localeCompare(right.title, "en", { sensitivity: "base" });
  return titleDifference || left.id.localeCompare(right.id);
}

export function buildSections(
  projects: ChatProject[],
  threads: ChatThread[],
  threadFilter: ThreadFilter = "all",
  multiAgentThreadIds: ReadonlySet<string> = new Set(),
  retainedUnreadThreadId: string | null = null,
  referenceTime: number = Date.now(),
): FolderSection[] {
  const visibleThreads = filterThreadsForSidebar(threads, threadFilter, multiAgentThreadIds, retainedUnreadThreadId, referenceTime);
  const projectSections: FolderSection[] = projects.map((project) => ({
    id: project.project_id,
    projectId: project.project_id,
    title: project.name,
    canManage: true,
    canCreateProject: false,
    canMoveThreads: true,
    emptyLabel: "No chats in this project.",
    items: [],
  }));
  const sectionsByProjectId = new Map(projectSections.map((section) => [section.projectId, section]));
  const placeholderSections: FolderSection[] = [];
  const unassigned: ChatThread[] = [];

  for (const thread of visibleThreads) {
    if (!thread.project_id) {
      unassigned.push(thread);
      continue;
    }
    let section = sectionsByProjectId.get(thread.project_id);
    if (!section) {
      section = {
        id: `project:${thread.project_id}`,
        projectId: thread.project_id,
        title: "Project",
        canManage: false,
        canCreateProject: false,
        canMoveThreads: true,
        emptyLabel: "No chats in this project.",
        items: [],
      };
      sectionsByProjectId.set(thread.project_id, section);
      placeholderSections.push(section);
    }
    section.items.push(thread);
  }

  const sections = [...projectSections, ...placeholderSections]
    .filter((section) => threadFilter === "all" || section.items.length > 0)
    .sort(compareProjectSections);
  if (unassigned.length || (threadFilter === "all" && !sections.length)) {
    sections.unshift({
      id: "unassigned",
      projectId: null,
      title: "No project",
      canManage: false,
      canCreateProject: true,
      canMoveThreads: true,
      emptyLabel: "No chats in this project.",
      items: unassigned,
    });
  }
  return sections;
}

export function filterThreads(
  threads: ChatThread[],
  threadFilter: ThreadFilter,
  multiAgentThreadIds: ReadonlySet<string> = new Set(),
  referenceTime: number = Date.now(),
): ChatThread[] {
  if (threadFilter === "hot") {
    return threads.filter((thread) => isThreadHot(thread, referenceTime));
  }
  if (threadFilter === "senses") {
    return threads.filter(isSensesThread);
  }
  if (threadFilter === "opendesign") {
    return threads.filter(isOpenDesignThread);
  }
  if (threadFilter === "multi_agent") {
    return threads.filter((thread) => isMultiAgentThread(thread, multiAgentThreadIds));
  }
  if (threadFilter === "unread") {
    return threads.filter(isThreadUnreadOrInProgress);
  }
  return threads;
}

export function filterThreadsForSidebar(
  threads: ChatThread[],
  threadFilter: ThreadFilter,
  multiAgentThreadIds: ReadonlySet<string> = new Set(),
  retainedUnreadThreadId: string | null = null,
  referenceTime: number = Date.now(),
): ChatThread[] {
  if (threadFilter === "unread" && retainedUnreadThreadId) {
    return threads.filter((thread) => thread.thread_id === retainedUnreadThreadId || isThreadUnreadOrInProgress(thread));
  }
  return filterThreads(threads, threadFilter, multiAgentThreadIds, referenceTime);
}

export function isSensesThread(thread: ChatThread): boolean {
  return sourceAppPresentation(thread.source_app_id)?.kind === "senses";
}

export function isOpenDesignThread(thread: ChatThread): boolean {
  return isOpenDesignSourceApp(thread.source_app_id);
}

export function isMultiAgentThread(thread: ChatThread, multiAgentThreadIds: ReadonlySet<string>): boolean {
  return multiAgentThreadIds.has(thread.thread_id) || multiAgentThreadIds.has(thread.runtime_session_id);
}

export function threadSourceBadges(thread: ChatThread, multiAgentThreadIds: ReadonlySet<string> = new Set()): ThreadSourceBadge[] {
  const badges: ThreadSourceBadge[] = [];
  const sourcePresentation = sourceAppPresentation(thread.source_app_id);
  if (sourcePresentation) {
    badges.push(sourcePresentation);
  }
  if (isMultiAgentThread(thread, multiAgentThreadIds)) {
    badges.push({ icon: "account_tree", kind: "multi_agent", label: "Multi-chat" });
  }
  return badges;
}

export function isThreadBusy(thread: ChatThread): boolean {
  return thread.availability === "busy" || thread.availability === "queued" || thread.availability === "active";
}

export function isThreadTitlePending(thread: ChatThread | null | undefined): boolean {
  return Boolean(thread?.title_pending);
}

export function isThreadHot(thread: ChatThread, referenceTime: number = Date.now()): boolean {
  const activityTime = threadLastMessageTimestamp(thread);
  const age = referenceTime - activityTime;
  return activityTime > 0 && age >= 0 && age <= HOT_THREAD_WINDOW_MS;
}

export function isThreadUnread(thread: ChatThread): boolean {
  return Boolean(thread.has_unread_completed_response) && !isThreadBusy(thread);
}

export function isThreadUnreadOrInProgress(thread: ChatThread): boolean {
  return isThreadUnread(thread) || isThreadBusy(thread);
}
