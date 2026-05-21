import { ApiError, requestJson } from "./http";
import type { ChatProject, ChatProjectsPayload, ChatSidebarPayload, ChatThread, DeleteThreadPayload } from "./types";

function threadTimestamp(value: string | null | undefined): number {
  if (!value) {
    return 0;
  }
  const parsed = Date.parse(value);
  return Number.isFinite(parsed) ? parsed : 0;
}

export function orderChatThreads(threads: ChatThread[]): ChatThread[] {
  return threads
    .slice()
    .sort((left, right) => {
      const leftUserMessageAt = threadTimestamp(left.last_user_message_at);
      const rightUserMessageAt = threadTimestamp(right.last_user_message_at);
      const leftHasUserMessage = leftUserMessageAt > 0;
      const rightHasUserMessage = rightUserMessageAt > 0;
      if (leftHasUserMessage !== rightHasUserMessage) {
        return rightHasUserMessage ? 1 : -1;
      }
      const leftRecency = leftHasUserMessage ? leftUserMessageAt : threadTimestamp(left.created_at);
      const rightRecency = rightHasUserMessage ? rightUserMessageAt : threadTimestamp(right.created_at);
      if (leftRecency !== rightRecency) {
        return rightRecency - leftRecency;
      }
      return left.thread_id.localeCompare(right.thread_id);
    });
}

export async function listChatProjects(): Promise<ChatProjectsPayload> {
  const payload = await requestJson<{ projects?: ChatProject[]; preferences?: Record<string, unknown> }>("/api/apps/chat/backend", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ action: "projects.list" }),
  });
  return { projects: payload.projects || [], preferences: payload.preferences };
}

async function withChatProjects<T extends { threads: ChatThread[] }>(payload: T): Promise<T & { projects: ChatProject[]; preferences?: Record<string, unknown> }> {
  const projectsPayload = await listChatProjects();
  return { ...payload, threads: orderChatThreads(payload.threads || []), ...projectsPayload };
}

export async function createThread(
  runtimeSessionId: string,
  projectId?: string | null,
  metadata: {
    agent_label?: string;
    agent_type_id?: string;
    agent_role_id?: string;
    source_app_id?: string;
    system_prompt?: string;
    title?: string;
  } = {},
): Promise<{ thread: ChatThread; threads: ChatThread[]; projects?: ChatProject[] }> {
  const payload = await requestJson<{ thread: ChatThread; threads: ChatThread[] }>("/api/runtime/threads", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ runtime_session_id: runtimeSessionId, project_id: projectId || null, ...metadata }),
  });
  return withChatProjects(payload);
}

export async function updateThread(payload: {
  thread_id: string;
  title?: string;
  runtime_session_id?: string;
  system_prompt?: string;
  project_id?: string | null;
  archived?: boolean;
}): Promise<{ thread: ChatThread; threads: ChatThread[]; projects?: ChatProject[] }> {
  const response = await requestJson<{ thread: ChatThread; threads: ChatThread[] }>(`/api/runtime/threads/${encodeURIComponent(payload.thread_id)}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  return withChatProjects(response);
}

export async function markThreadRead(threadId: string): Promise<{ thread: ChatThread; threads: ChatThread[]; projects?: ChatProject[] }> {
  const response = await requestJson<{ thread: ChatThread; threads: ChatThread[] }>(`/api/runtime/threads/${encodeURIComponent(threadId)}/read`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
  });
  return withChatProjects(response);
}

export async function deleteThread(threadId: string): Promise<ChatSidebarPayload> {
  const payload = await requestJson<DeleteThreadPayload>(`/api/runtime/threads/${encodeURIComponent(threadId)}`, {
    method: "DELETE",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ reason: "chat_thread_deleted" }),
  });
  return withChatProjects(payload);
}

export async function createProject(name: string): Promise<{ project: ChatProject } & ChatProjectsPayload> {
  const projectPayload = await requestJson<{ project: ChatProject; projects?: ChatProject[]; preferences?: Record<string, unknown> }>("/api/apps/chat/backend", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ action: "projects.create", name }),
  });
  return { ...projectPayload, projects: projectPayload.projects || [] };
}

export async function updateProject(projectId: string, name: string): Promise<{ project: ChatProject } & ChatProjectsPayload> {
  const projectPayload = await requestJson<{ project: ChatProject; projects?: ChatProject[]; preferences?: Record<string, unknown> }>("/api/apps/chat/backend", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ action: "projects.update", project_id: projectId, name }),
  });
  return { ...projectPayload, projects: projectPayload.projects || [] };
}

export async function deleteProject(projectId: string): Promise<ChatProjectsPayload> {
  const backendPath = "/api/apps/chat/backend";
  const projectPayload = await requestJson<{ projects?: ChatProject[]; preferences?: Record<string, unknown> }>(backendPath, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ action: "projects.delete", project_id: projectId }),
  });
  if (!Array.isArray(projectPayload.projects)) {
    throw new ApiError("Project deletion did not return updated projects.", { path: backendPath, status: 502 });
  }
  return { projects: projectPayload.projects, preferences: projectPayload.preferences };
}
