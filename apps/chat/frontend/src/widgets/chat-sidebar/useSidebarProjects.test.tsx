/** @vitest-environment happy-dom */
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { ChatProject } from "../../api/client";
import { useSidebarProjects } from "./useSidebarProjects";

const mocks = vi.hoisted(() => ({ read: vi.fn() }));
vi.mock("../../pwaCache", () => ({ readChatDisplay: mocks.read }));

const project: ChatProject = { project_id: "p", name: "Named project", created_at: "2026-09-06", updated_at: "2026-09-06" };
const page = { projects: [project], has_more: false };
let state: ReturnType<typeof useSidebarProjects>;
let root: Root | null;
let container: HTMLDivElement;

function Probe() {
  state = useSidebarProjects();
  return null;
}

async function mount() {
  await act(async () => { root!.render(<Probe />); });
}

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (error: unknown) => void;
  const promise = new Promise<T>((yes, no) => { resolve = yes; reject = no; });
  return { promise, resolve, reject };
}

beforeEach(() => {
  mocks.read.mockReset().mockResolvedValue(page);
  vi.spyOn(document, "hidden", "get").mockReturnValue(false);
  container = document.createElement("div");
  document.body.append(container);
  root = createRoot(container);
});

afterEach(async () => {
  await act(async () => { root?.unmount(); });
  root = null;
  container.remove();
  vi.restoreAllMocks();
});

describe("sidebar project read lifecycle", () => {
  it.each(["online", "focus", "visibilitychange"])("recovers a failed read on %s without polling a healthy catalog", async (name) => {
    mocks.read.mockRejectedValueOnce(new Error("Catalog read failed"));
    await mount();
    expect(state.error).toBe("Catalog read failed");
    const target = name === "visibilitychange" ? document : window;
    await act(async () => { target.dispatchEvent(new Event(name)); });
    expect(state.projects).toEqual([project]);
    expect(state.error).toBeNull();
    await act(async () => { target.dispatchEvent(new Event(name)); });
    expect(mocks.read).toHaveBeenCalledTimes(2);
  });

  it("does not restart a pending read or reload a successfully empty catalog", async () => {
    const pending = deferred<{ projects: ChatProject[]; has_more: boolean }>();
    mocks.read.mockReturnValueOnce(pending.promise);
    await mount();
    await act(async () => { window.dispatchEvent(new Event("online")); });
    expect(mocks.read).toHaveBeenCalledTimes(1);
    await act(async () => { pending.resolve({ projects: [], has_more: false }); });
    await act(async () => { window.dispatchEvent(new Event("focus")); });
    expect(mocks.read).toHaveBeenCalledTimes(1);
    expect(state.projects).toEqual([]);
    expect(state.error).toBeNull();
  });

  it("retains cached names and reports a failed revalidation until a fresh read succeeds", async () => {
    await mount();
    await act(async () => { mocks.read.mock.calls[0][1].onRevalidationError(new Error("Revalidation failed")); });
    expect(state.projects).toEqual([project]);
    expect(state.error).toBe("Revalidation failed");
    await act(async () => { await state.refresh(); });
    expect(state.error).toBeNull();
  });

  it("ignores late errors and revalidation from a superseded read", async () => {
    const pending = deferred<typeof page>();
    mocks.read.mockReturnValueOnce(pending.promise);
    await mount();
    const oldOptions = mocks.read.mock.calls[0][1];
    await act(async () => { await state.refresh(); });
    expect(oldOptions.signal.aborted).toBe(true);
    await act(async () => {
      pending.reject(new Error("Old request failed"));
      oldOptions.onRevalidationError(new Error("Old cache failed"));
      oldOptions.onRevalidated({ projects: [], has_more: false });
    });
    expect(state.projects).toEqual([project]);
    expect(state.error).toBeNull();
    expect(state.isLoading).toBe(false);
  });

  it("keeps a newer mutation projection instead of an older pending display read", async () => {
    const pending = deferred<typeof page>();
    mocks.read.mockReturnValueOnce(pending.promise);
    await mount();
    const renamed = { ...project, name: "Renamed" };
    await act(async () => { state.replaceProjects([renamed]); pending.resolve(page); });
    expect(state.projects).toEqual([renamed]);
    expect(mocks.read.mock.calls[0][1].signal.aborted).toBe(true);
    expect(state.isLoading).toBe(false);
  });

  it("aborts on unmount and removes recovery listeners", async () => {
    const pending = deferred<typeof page>();
    mocks.read.mockReturnValueOnce(pending.promise);
    await mount();
    const signal = mocks.read.mock.calls[0][1].signal;
    await act(async () => { root!.unmount(); root = null; pending.reject(new Error("Late failure")); });
    expect(signal.aborted).toBe(true);
    window.dispatchEvent(new Event("online"));
    window.dispatchEvent(new Event("focus"));
    document.dispatchEvent(new Event("visibilitychange"));
    expect(mocks.read).toHaveBeenCalledTimes(1);
  });
});
