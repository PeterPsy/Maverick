import { ChatProject, ChatThread } from "../../api/client";

export type FolderSection = {
  id: string;
  projectId: string | null;
  title: string;
  items: ChatThread[];
  canManage: boolean;
};

export function buildSections(projects: ChatProject[], threads: ChatThread[]): FolderSection[] {
  const projectSections: FolderSection[] = projects
    .slice()
    .sort((left, right) => left.name.localeCompare(right.name, "en", { sensitivity: "base" }))
    .map((project) => ({
      id: project.project_id,
      projectId: project.project_id,
      title: project.name,
      canManage: true,
      items: [],
    }));
  const sectionsByProjectId = new Map(projectSections.map((section) => [section.projectId, section]));
  const placeholderSections: FolderSection[] = [];
  const unassigned: ChatThread[] = [];

  for (const thread of threads) {
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
        items: [],
      };
      sectionsByProjectId.set(thread.project_id, section);
      placeholderSections.push(section);
    }
    section.items.push(thread);
  }

  const sections = [...projectSections, ...placeholderSections];
  if (unassigned.length || !sections.length) {
    sections.unshift({
      id: "unassigned",
      projectId: null,
      title: "No project",
      canManage: false,
      items: unassigned,
    });
  }
  return sections;
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
