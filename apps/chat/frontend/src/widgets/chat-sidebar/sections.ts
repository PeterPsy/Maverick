import { ChatProject, ChatThread } from "../../api/client";

export type FolderSection = {
  id: string;
  projectId: string | null;
  title: string;
  items: ChatThread[];
  canManage: boolean;
};

export function buildSections(projects: ChatProject[], threads: ChatThread[]): FolderSection[] {
  const sections: FolderSection[] = projects
    .slice()
    .sort((left, right) => left.name.localeCompare(right.name, "it", { sensitivity: "base" }))
    .map((project) => ({
      id: project.project_id,
      projectId: project.project_id,
      title: project.name,
      canManage: true,
      items: threads.filter((thread) => thread.project_id === project.project_id),
    }));
  const projectIds = new Set(projects.map((project) => project.project_id));
  const unassigned = threads.filter((thread) => !thread.project_id || !projectIds.has(thread.project_id));
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
