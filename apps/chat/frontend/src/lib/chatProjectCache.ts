import type { ChatProject } from "../api/client";

const STORAGE_KEY_PREFIX = "maverick.chat.projects-cache.v1:";
const MAX_CACHED_PROJECTS = 200;

type StoredChatProjectCache = {
  projects?: unknown;
};

function storage(): Storage | null {
  if (typeof window === "undefined") {
    return null;
  }
  try {
    return window.localStorage;
  } catch {
    return null;
  }
}

function storageKey(workspaceId: string): string {
  return `${STORAGE_KEY_PREFIX}${workspaceId}`;
}

function normalizeProject(value: unknown): ChatProject | null {
  if (!value || typeof value !== "object") {
    return null;
  }
  const record = value as Record<string, unknown>;
  const projectId = typeof record.project_id === "string" ? record.project_id.trim() : "";
  const name = typeof record.name === "string" ? record.name.trim() : "";
  const createdAt = typeof record.created_at === "string" ? record.created_at : "";
  const updatedAt = typeof record.updated_at === "string" ? record.updated_at : "";
  if (!projectId || !name) {
    return null;
  }
  return {
    project_id: projectId,
    name,
    created_at: createdAt,
    updated_at: updatedAt,
  };
}

function normalizedWorkspaceId(workspaceId: string): string {
  return workspaceId.trim();
}

export function readStoredChatProjects(workspaceId: string): ChatProject[] {
  const normalized = normalizedWorkspaceId(workspaceId);
  const targetStorage = normalized ? storage() : null;
  if (!targetStorage) {
    return [];
  }
  try {
    const rawValue = targetStorage.getItem(storageKey(normalized));
    if (!rawValue) {
      return [];
    }
    const payload = JSON.parse(rawValue) as StoredChatProjectCache;
    if (!Array.isArray(payload.projects)) {
      return [];
    }
    return payload.projects.map(normalizeProject).filter((project): project is ChatProject => Boolean(project));
  } catch {
    return [];
  }
}

export function writeStoredChatProjects(workspaceId: string, projects: ChatProject[]): void {
  const normalized = normalizedWorkspaceId(workspaceId);
  const targetStorage = normalized ? storage() : null;
  if (!targetStorage) {
    return;
  }
  try {
    targetStorage.setItem(
      storageKey(normalized),
      JSON.stringify({
        projects: projects.slice(0, MAX_CACHED_PROJECTS),
      }),
    );
  } catch {
    // Project metadata is a performance hint; storage failures should not affect the sidebar.
  }
}
