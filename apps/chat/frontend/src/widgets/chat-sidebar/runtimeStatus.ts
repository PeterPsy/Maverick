import { ChatThread, listRuntimeTurns, RuntimeTurn } from "../../api/client";

const activeTurnStatuses = new Set(["queued", "active"]);

export function hasActiveRuntimeTurn(turns: RuntimeTurn[]): boolean {
  return turns.some((turn) => activeTurnStatuses.has(turn.status));
}

export async function withRuntimeAvailability(
  threads: ChatThread[],
  fetchRuntimeTurns: (sessionId: string) => Promise<{ items: RuntimeTurn[] }> = listRuntimeTurns,
): Promise<ChatThread[]> {
  const sessionIds = Array.from(new Set(threads.map((thread) => thread.runtime_session_id).filter(Boolean)));
  if (!sessionIds.length) {
    return threads;
  }
  const results = await Promise.allSettled(sessionIds.map((sessionId) => fetchRuntimeTurns(sessionId)));
  const busySessionIds = new Set<string>();
  const checkedSessionIds = new Set<string>();
  results.forEach((result, index) => {
    const sessionId = sessionIds[index];
    if (result.status !== "fulfilled") {
      return;
    }
    checkedSessionIds.add(sessionId);
    if (hasActiveRuntimeTurn(result.value.items || [])) {
      busySessionIds.add(sessionId);
    }
  });
  return threads.map((thread) => {
    if (!thread.runtime_session_id) {
      return { ...thread, availability: "free" };
    }
    if (!checkedSessionIds.has(thread.runtime_session_id)) {
      return thread;
    }
    return {
      ...thread,
      availability: busySessionIds.has(thread.runtime_session_id) ? "busy" : "free",
    };
  });
}
