import { ChatProject, ChatThread } from "../../api/client";

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

export type ThreadFilter = "all" | "senses" | "multi_agent" | "unread";

export type ThreadSourceBadge = {
  icon: string;
  kind: "multi_agent" | "senses";
  label: string;
};

export function buildSections(
  projects: ChatProject[],
  threads: ChatThread[],
  threadFilter: ThreadFilter = "all",
  multiAgentThreadIds: ReadonlySet<string> = new Set(),
): FolderSection[] {
  const visibleThreads = filterThreads(threads, threadFilter, multiAgentThreadIds);
  const projectSections: FolderSection[] = projects
    .slice()
    .sort((left, right) => left.name.localeCompare(right.name, "en", { sensitivity: "base" }))
    .map((project) => ({
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

  const sections = [...projectSections, ...placeholderSections].filter(
    (section) => threadFilter === "all" || section.items.length > 0,
  );
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
): ChatThread[] {
  if (threadFilter === "senses") {
    return threads.filter(isSensesThread);
  }
  if (threadFilter === "multi_agent") {
    return threads.filter((thread) => isMultiAgentThread(thread, multiAgentThreadIds));
  }
  if (threadFilter === "unread") {
    return threads.filter(isThreadUnread);
  }
  return threads;
}

export function isSensesThread(thread: ChatThread): boolean {
  return thread.source_app_id === "senses";
}

export function isMultiAgentThread(thread: ChatThread, multiAgentThreadIds: ReadonlySet<string>): boolean {
  return multiAgentThreadIds.has(thread.thread_id) || multiAgentThreadIds.has(thread.runtime_session_id);
}

export function threadSourceBadges(thread: ChatThread, multiAgentThreadIds: ReadonlySet<string> = new Set()): ThreadSourceBadge[] {
  const badges: ThreadSourceBadge[] = [];
  if (isSensesThread(thread)) {
    badges.push({ icon: "sensors", kind: "senses", label: "Senses" });
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

export function isThreadUnread(thread: ChatThread): boolean {
  return Boolean(thread.has_unread_completed_response) && !isThreadBusy(thread);
}
