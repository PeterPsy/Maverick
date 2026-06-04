import { type Dispatch, type SetStateAction, useEffect, useRef, useState } from "react";
import type { ChatProject, ChatThread } from "../../api/client";
import { createProject, deleteProject, updateProject } from "../../api/client";
import { projectDeletionConfirmationMessage, updateFromSidebarPayload } from "./chatSidebarStateUtils";
import type { PendingProjectDeletion } from "./chatSidebarStateUtils";

type UseSidebarProjectActionsParams = {
  activeThreadId: string | null;
  projects: ChatProject[];
  setActiveThreadId: Dispatch<SetStateAction<string | null>>;
  setError: Dispatch<SetStateAction<string | null>>;
  setExpandedThreadId: Dispatch<SetStateAction<string | null>>;
  setExpandedThreadTitle: Dispatch<SetStateAction<string>>;
  setIsPending: Dispatch<SetStateAction<boolean>>;
  setProjects: (projects: ChatProject[]) => void;
  setThreads: Dispatch<SetStateAction<ChatThread[]>>;
  threads: ChatThread[];
};

export function useSidebarProjectActions({
  activeThreadId,
  projects,
  setActiveThreadId,
  setError,
  setExpandedThreadId,
  setExpandedThreadTitle,
  setIsPending,
  setProjects,
  setThreads,
  threads,
}: UseSidebarProjectActionsParams) {
  const [editingProject, setEditingProject] = useState<{ projectId: string; name: string } | null>(null);
  const [pendingProjectDeletion, setPendingProjectDeletion] = useState<PendingProjectDeletion | null>(null);
  const editingProjectRef = useRef<HTMLElement | null>(null);

  useEffect(() => {
    if (!editingProject) {
      return;
    }
    function cancelProjectEditFromOutside(event: PointerEvent) {
      const target = event.target;
      if (target instanceof Node && editingProjectRef.current?.contains(target)) {
        return;
      }
      clearProjectEditing();
    }
    document.addEventListener("pointerdown", cancelProjectEditFromOutside);
    return () => document.removeEventListener("pointerdown", cancelProjectEditFromOutside);
  }, [editingProject?.projectId]);

  function clearProjectEditing() {
    setEditingProject(null);
    setPendingProjectDeletion(null);
  }

  async function addProject() {
    setIsPending(true);
    try {
      const payload = await createProject("New project");
      updateFromSidebarPayload(payload, setProjects);
      clearProjectEditing();
      setError(null);
    } catch (projectError) {
      setError(projectError instanceof Error ? projectError.message : "Unable to create project.");
    } finally {
      setIsPending(false);
    }
  }

  async function renameProject(projectId: string, name: string) {
    const payload = await updateProject(projectId, name);
    updateFromSidebarPayload(payload, setProjects);
    setExpandedThreadId(null);
    setExpandedThreadTitle("");
    clearProjectEditing();
  }

  async function removeProject(projectId: string) {
    const payload = await deleteProject(projectId);
    updateFromSidebarPayload(payload, setProjects);
    setThreads((current) => current.filter((thread) => thread.project_id !== projectId));
    if (threads.some((thread) => thread.thread_id === activeThreadId && thread.project_id === projectId)) {
      setActiveThreadId(null);
    }
    clearProjectEditing();
  }

  function startProjectEdit(project: ChatProject) {
    setExpandedThreadId(null);
    setExpandedThreadTitle("");
    setEditingProject({ projectId: project.project_id, name: project.name });
    setPendingProjectDeletion(null);
    setError(null);
  }

  function setEditingProjectName(name: string) {
    setEditingProject((current) => (current ? { ...current, name } : current));
  }

  async function saveProjectEdit() {
    if (!editingProject) {
      return;
    }
    const nextName = editingProject.name.trim();
    if (!nextName) {
      setError("Project name cannot be empty.");
      return;
    }
    const project = projects.find((item) => item.project_id === editingProject.projectId);
    if (project?.name === nextName) {
      clearProjectEditing();
      return;
    }
    setIsPending(true);
    try {
      await renameProject(editingProject.projectId, nextName);
      setError(null);
    } catch (projectError) {
      setError(projectError instanceof Error ? projectError.message : "Unable to save project.");
    } finally {
      setIsPending(false);
    }
  }

  function removeEditingProject(projectId: string) {
    const project = projects.find((item) => item.project_id === projectId);
    const linkedThreadCount = threads.filter((thread) => thread.project_id === projectId).length;
    setPendingProjectDeletion({
      message: projectDeletionConfirmationMessage(project, linkedThreadCount),
      projectId,
    });
    setError(null);
  }

  async function confirmProjectDeletion(projectId: string) {
    setIsPending(true);
    try {
      await removeProject(projectId);
      setError(null);
    } catch (projectError) {
      setError(projectError instanceof Error ? projectError.message : "Unable to delete project.");
    } finally {
      setIsPending(false);
    }
  }

  return {
    addProject,
    cancelProjectDeletion: () => setPendingProjectDeletion(null),
    cancelProjectEdit: clearProjectEditing,
    clearProjectEditing,
    confirmProjectDeletion,
    editingProject,
    editingProjectRef,
    pendingProjectDeletion,
    removeEditingProject,
    saveProjectEdit,
    setEditingProjectName,
    startProjectEdit,
  };
}
