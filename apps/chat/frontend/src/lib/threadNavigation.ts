import { ChatThread } from "../api/client";

export function findThreadByRuntimeSession(threads: ChatThread[], runtimeSessionId: string): ChatThread | null {
  return threads.find((thread) => thread.runtime_session_id === runtimeSessionId) || null;
}
