import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { applyThreadCatalogPayload, deleteThread, deleteThreads } from "./chatProjects";
import type { ChatThread } from "./types";

describe("applyThreadCatalogPayload", () => {
  it("merges a changed thread without requiring a full catalog", () => {
    const original = thread({ thread_id: "thread-1", runtime_session_id: "session-1", title: "Original" });
    const unchanged = thread({
      thread_id: "thread-2",
      runtime_session_id: "session-2",
      title: "Unchanged",
      created_at: "2026-06-29T00:00:01.000Z",
      updated_at: "2026-06-29T00:00:01.000Z",
    });
    const changed = { ...original, title: "Renamed", updated_at: "2026-06-29T00:00:02.000Z" };

    expect(applyThreadCatalogPayload([original, unchanged], { changed_thread: changed })).toEqual([unchanged, changed]);
  });

  it("removes deleted threads from a delta payload", () => {
    const first = thread({ thread_id: "thread-1", runtime_session_id: "session-1" });
    const second = thread({ thread_id: "thread-2", runtime_session_id: "session-2" });
    const third = thread({ thread_id: "thread-3", runtime_session_id: "session-3" });

    expect(applyThreadCatalogPayload([first, second, third], { deleted_thread_id: "thread-2" })).toEqual([first, third]);
    expect(applyThreadCatalogPayload([first, second, third], { removed_thread_id: "thread-3" })).toEqual([first, second]);
  });

  it("keeps full catalog payloads as an ordered compatibility path", () => {
    const older = thread({ thread_id: "thread-old", runtime_session_id: "session-old" });
    const newer = thread({
      thread_id: "thread-new",
      runtime_session_id: "session-new",
      created_at: "2026-06-29T00:00:01.000Z",
      updated_at: "2026-06-29T00:00:01.000Z",
    });

    expect(applyThreadCatalogPayload([], { threads: [older, newer] })).toEqual([newer, older]);
  });
});

describe("thread delete API", () => {
  beforeEach(() => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async (path: string) =>
        okJson(
          path.endsWith("delete-batch")
            ? {
                deleted_thread_ids: ["thread-1", "thread-2"],
                deleted_runtime_session_ids: ["session-1", "session-2"],
                results: [
                  { thread_id: "thread-1", runtime_session_id: "session-1", status: "deleted" },
                  { thread_id: "thread-2", runtime_session_id: "session-2", status: "deleted" },
                ],
              }
            : { deleted_thread_id: "thread-1", deleted_runtime_session_id: "session-1" },
        ),
      ),
    );
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("does not reload Chat projects after deleting one thread", async () => {
    await deleteThread("thread-1");

    expect(fetch).toHaveBeenCalledTimes(1);
    expect(fetch).toHaveBeenCalledWith(
      "/api/runtime/threads/thread-1",
      expect.objectContaining({ method: "DELETE" }),
    );
  });

  it("deletes a selection with one batch request", async () => {
    await deleteThreads(["thread-1", "thread-2"]);

    expect(fetch).toHaveBeenCalledTimes(1);
    expect(fetch).toHaveBeenCalledWith(
      "/api/runtime/threads/delete-batch",
      expect.objectContaining({
        body: JSON.stringify({ reason: "chat_threads_deleted", thread_ids: ["thread-1", "thread-2"] }),
        keepalive: true,
        method: "POST",
      }),
    );
  });

  it("sends a typical complete sidebar catalog in one request", async () => {
    const threadIds = Array.from({ length: 165 }, (_, index) => `thread-${index + 1}`);
    vi.mocked(fetch).mockImplementation(async (_path: string | URL | Request, init?: RequestInit) => {
      const body = JSON.parse(String(init?.body)) as { thread_ids: string[] };
      return okJson({
        deleted_thread_ids: body.thread_ids,
        deleted_runtime_session_ids: body.thread_ids.map((threadId) => `session-${threadId}`),
        results: body.thread_ids.map((threadId) => ({
          thread_id: threadId,
          runtime_session_id: `session-${threadId}`,
          status: "deleted",
        })),
      });
    });

    const payload = await deleteThreads(threadIds);

    expect(fetch).toHaveBeenCalledTimes(1);
    expect(fetch).toHaveBeenCalledWith(
      "/api/runtime/threads/delete-batch",
      expect.objectContaining({
        body: JSON.stringify({ reason: "chat_threads_deleted", thread_ids: threadIds }),
        keepalive: true,
      }),
    );
    expect(payload.deleted_thread_ids).toEqual(threadIds);
    expect(payload.deleted_runtime_session_ids).toEqual(
      threadIds.map((threadId) => `session-${threadId}`),
    );
    expect(payload.results.map((result) => result.thread_id)).toEqual(threadIds);
  });

  it("reports each successful chunk before a later oversized-selection chunk fails", async () => {
    const threadIds = Array.from({ length: 501 }, (_, index) => `thread-${index + 1}`);
    vi.mocked(fetch)
      .mockImplementationOnce(async (_path: string | URL | Request, init?: RequestInit) => {
        const body = JSON.parse(String(init?.body)) as { thread_ids: string[] };
        return okJson({
          deleted_thread_ids: body.thread_ids,
          deleted_runtime_session_ids: body.thread_ids.map((threadId) => `session-${threadId}`),
          results: body.thread_ids.map((threadId) => ({
            thread_id: threadId,
            runtime_session_id: `session-${threadId}`,
            status: "deleted",
          })),
        });
      })
      .mockRejectedValueOnce(new Error("connection closed"));
    const onBatchComplete = vi.fn();

    await expect(deleteThreads(threadIds, onBatchComplete)).rejects.toThrow("connection closed");

    expect(fetch).toHaveBeenCalledTimes(2);
    expect(onBatchComplete).toHaveBeenCalledTimes(1);
    expect(onBatchComplete.mock.calls[0]?.[0].deleted_thread_ids).toEqual(threadIds.slice(0, 500));
  });
});

function okJson(payload: unknown): Response {
  return {
    ok: true,
    status: 200,
    json: async () => payload,
  } as Response;
}

function thread(overrides: Partial<ChatThread>): ChatThread {
  return {
    thread_id: "thread",
    runtime_session_id: "session",
    title: "Thread",
    agent_label: "chat",
    agent_type_id: "",
    agent_role_id: "",
    source_app_id: "chat",
    system_prompt: "",
    project_id: null,
    archived: false,
    availability: "free",
    created_at: "2026-06-29T00:00:00.000Z",
    updated_at: "2026-06-29T00:00:00.000Z",
    ...overrides,
  };
}
