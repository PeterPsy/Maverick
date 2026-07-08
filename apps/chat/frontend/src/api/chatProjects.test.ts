import { describe, expect, it } from "vitest";
import { applyThreadCatalogPayload } from "./chatProjects";
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
