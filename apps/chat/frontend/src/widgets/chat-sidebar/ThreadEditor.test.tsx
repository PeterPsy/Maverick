/** @vitest-environment happy-dom */
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { ChatThread } from "../../api/client";
import { ThreadEditor } from "./ThreadEditor";

const thread: ChatThread = {
  thread_id: "thread",
  runtime_session_id: "session",
  title: "Budget notes",
  project_id: null,
  source_app_id: "chat",
  archived: false,
  availability: "free",
  agent_label: "Chat",
  agent_role_id: "",
  agent_type_id: "",
  system_prompt: "",
  created_at: "2026-10-08T10:00:00Z",
  updated_at: "2026-10-08T10:00:00Z",
};

describe("ThreadEditor", () => {
  let root: Root;
  let container: HTMLDivElement;
  const close = vi.fn();
  const rename = vi.fn();
  const remove = vi.fn();

  afterEach(() => {
    act(() => root?.unmount());
    container?.remove();
    vi.resetAllMocks();
  });

  async function render(title = "Updated budget", item = thread) {
    container = document.createElement("div");
    document.body.append(container);
    root = createRoot(container);
    await act(async () => {
      root.render(
        <ThreadEditor
          thread={item}
          title={title}
          projects={[]}
          onTitleChange={vi.fn()}
          onClose={close}
          onRenameThread={rename}
          onDeleteThread={remove}
        />,
      );
    });
  }

  function button(label: string) {
    const result = [
      ...container.querySelectorAll<HTMLButtonElement>("button"),
    ].find(
      (element) =>
        element.textContent === label ||
        element.getAttribute("aria-label") === label,
    );
    if (!result) throw new Error(`Missing button ${label}`);
    return result;
  }

  async function submit() {
    await act(async () => {
      container
        .querySelector("form")!
        .dispatchEvent(
          new Event("submit", { bubbles: true, cancelable: true }),
        );
    });
  }

  it("submits a trimmed title once and blocks edits or dismissal while saving", async () => {
    let finish!: () => void;
    rename.mockReturnValue(
      new Promise<void>((resolve) => {
        finish = resolve;
      }),
    );
    await render("  Updated budget  ");
    await submit();
    await submit();
    expect(rename).toHaveBeenCalledExactlyOnceWith(
      "thread",
      "Updated budget",
      null,
    );
    expect(container.querySelector<HTMLInputElement>("input")?.disabled).toBe(
      true,
    );
    expect(container.querySelector<HTMLSelectElement>("select")?.disabled).toBe(
      true,
    );
    await act(async () => {
      container
        .querySelector("input")!
        .dispatchEvent(
          new KeyboardEvent("keydown", { key: "Escape", bubbles: true }),
        );
    });
    expect(close).not.toHaveBeenCalled();
    await act(async () => {
      finish();
    });
    expect(close).toHaveBeenCalledOnce();
  });

  it("keeps the draft and current project after a save failure and supports retry", async () => {
    rename
      .mockRejectedValueOnce(new Error("Save unavailable"))
      .mockResolvedValueOnce(undefined);
    await render("Updated budget", { ...thread, project_id: "uncatalogued" });
    await submit();
    expect(close).not.toHaveBeenCalled();
    expect(container.querySelector('[role="alert"]')?.textContent).toBe(
      "Save unavailable",
    );
    expect(container.querySelector<HTMLInputElement>("input")?.value).toBe(
      "Updated budget",
    );
    expect(container.querySelector<HTMLSelectElement>("select")?.value).toBe(
      "uncatalogued",
    );
    await submit();
    expect(rename).toHaveBeenLastCalledWith(
      "thread",
      "Updated budget",
      "uncatalogued",
    );
    expect(close).toHaveBeenCalledOnce();
  });

  it("requires confirmation before deletion and allows cancellation and retry", async () => {
    remove
      .mockRejectedValueOnce(new Error("Delete unavailable"))
      .mockResolvedValueOnce(undefined);
    await render();
    await act(async () => {
      button("Delete Budget notes").click();
    });
    expect(remove).not.toHaveBeenCalled();
    await act(async () => {
      button("Keep chat").click();
    });
    expect(remove).not.toHaveBeenCalled();
    await act(async () => {
      button("Delete Budget notes").click();
    });
    await act(async () => {
      button("Delete chat").click();
    });
    expect(container.querySelector('[role="alert"]')?.textContent).toBe(
      "Delete unavailable",
    );
    expect(close).not.toHaveBeenCalled();
    await act(async () => {
      button("Delete chat").click();
    });
    expect(remove).toHaveBeenCalledTimes(2);
    expect(close).toHaveBeenCalledOnce();
  });

  it("prevents unchanged saves and lets Escape back out of confirmation first", async () => {
    await render(thread.title);
    expect(button("Save").disabled).toBe(true);
    await submit();
    expect(rename).not.toHaveBeenCalled();
    await act(async () => {
      button("Delete Budget notes").click();
    });
    await act(async () => {
      container
        .querySelector("input")!
        .dispatchEvent(
          new KeyboardEvent("keydown", { key: "Escape", bubbles: true }),
        );
    });
    expect(close).not.toHaveBeenCalled();
    expect(button("Save")).toBeDefined();
    await act(async () => {
      container
        .querySelector("input")!
        .dispatchEvent(
          new KeyboardEvent("keydown", { key: "Escape", bubbles: true }),
        );
    });
    expect(close).toHaveBeenCalledOnce();
  });
});
