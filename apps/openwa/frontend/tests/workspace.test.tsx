import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { callBackend, operation, type Session, type Status } from "../src/api";
import { useWorkspace } from "../src/useWorkspace";
import { useResources } from "../src/useResources";
import { App } from "../src/App";

vi.mock("../src/api", async (original) => ({ ...await original(), operation: vi.fn(), callBackend: vi.fn() }));
vi.mock("@loopino/pwa-cache", () => ({
  loopinoAppIsVisible: () => true,
  observeLoopinoVisibility: (listener: (visible: boolean) => void) => { listener(true); return () => {}; },
  connectAppEventSocket: () => () => {},
  isExactLoopinoParentMessage: () => false,
}));
const status: Status = { send_scope: "scope-a", can_configure: true,
  connection: { url: "https://example.com", configured: true, credential_available: true, role: "operator" },
  source: { repository: "example", version: "0.24" } };
const sessions: Session[] = [{ id: "one", name: "First", status: "ready" }, { id: "two", name: "Second", status: "ready" }];
const backend = vi.mocked(callBackend), request = vi.mocked(operation);
let workspace: ReturnType<typeof useWorkspace>;
let resources: ReturnType<typeof useResources>;
let container: HTMLDivElement;
let root: Root;
function WorkspaceProbe() { workspace = useWorkspace(); return null; }
function ResourceProbe({ page = 0, session = sessions[0] }) {
  resources = useResources(session, "chats", page, true, 0);
  return <p>{resources.chats.map((chat) => chat.name).join(",")}{resources.error}</p>;
}
beforeEach(() => {
  (globalThis as Record<string, unknown>).IS_REACT_ACT_ENVIRONMENT = true;
  vi.useFakeTimers();
  backend.mockReset().mockResolvedValue(status);
  request.mockReset().mockResolvedValue(sessions);
  container = document.createElement("div");
  document.body.append(container);
  root = createRoot(container);
});
afterEach(async () => { await act(async () => root.unmount()); container.remove(); vi.useRealTimers(); });

it("preserves a user selection made during a slow session refresh", async () => {
  await act(async () => root.render(<WorkspaceProbe />));
  let finish!: (data: unknown) => void;
  request.mockImplementationOnce(() => new Promise((resolve) => { finish = resolve; }));
  await act(async () => { void workspace.refresh(); });
  await act(async () => workspace.setSelected("two"));
  await act(async () => finish(sessions));
  expect(workspace.selected).toBe("two");
});

it("clears previous gateway data even when the new session read fails", async () => {
  await act(async () => root.render(<WorkspaceProbe />));
  expect(workspace.sessions).toHaveLength(2);
  backend.mockResolvedValue({ ...status, send_scope: "scope-b" });
  request.mockRejectedValueOnce(new Error("New gateway unavailable"));
  await act(async () => { await workspace.refresh(); });
  expect(workspace.sessions).toEqual([]);
  expect(workspace.selected).toBe("");
  expect(workspace.online).toBe(false);
  expect(workspace.error).toBe("New gateway unavailable");
});

it("removes session data and skips provider reads after credentials disappear", async () => {
  await act(async () => root.render(<WorkspaceProbe />));
  backend.mockResolvedValue({ ...status, connection: { ...status.connection, credential_available: false } });
  request.mockClear();
  await act(async () => { await workspace.refresh(); });
  expect(workspace.sessions).toEqual([]);
  expect(request).not.toHaveBeenCalled();
});

it("hides previous pages immediately and rejects their late responses", async () => {
  request.mockResolvedValueOnce([{ id: "first@c.us", name: "Old page" }]);
  await act(async () => root.render(<ResourceProbe />));
  let finish!: (data: unknown) => void;
  request.mockImplementationOnce(() => new Promise((resolve) => { finish = resolve; }));
  await act(async () => { void resources.refresh(); });
  const oldSignal = request.mock.calls[1][2]!;
  request.mockResolvedValueOnce([{ id: "second@c.us", name: "New page" }]);
  await act(async () => root.render(<ResourceProbe page={1} />));
  expect(oldSignal.aborted).toBe(true);
  expect(container.textContent).toBe("New page");
  await act(async () => finish([{ id: "late@c.us", name: "Stale response" }]));
  expect(container.textContent).toBe("New page");
});

it("retains current rows on a read failure and clears only the recovered read error", async () => {
  request.mockResolvedValueOnce([{ id: "first@c.us", name: "Alice" }]);
  await act(async () => root.render(<ResourceProbe />));
  request.mockRejectedValueOnce(new Error("Rate limited"));
  await act(async () => { await resources.refresh(); });
  expect(container.textContent).toBe("AliceRate limited");
  request.mockResolvedValueOnce([{ id: "first@c.us", name: "Alice" }]);
  await act(async () => { await resources.refresh(); });
  expect(container.textContent).toBe("Alice");
});

it("resets pagination atomically when changing resource tabs", async () => {
  request.mockImplementation(async (action) => action === "sessions.list" ? sessions :
    action === "chats.list" ? Array.from({ length: 50 }, (_, index) => ({ id: `${index}@c.us`, name: `Chat ${index}` })) : []);
  await act(async () => root.render(<App />));
  const button = (text: string) => [...container.querySelectorAll("button")].find((node) => node.textContent === text)!;
  await act(async () => button("Next").click());
  expect(request.mock.calls.some(([action, body]) => action === "chats.list" && body?.offset === 50)).toBe(true);
  await act(async () => button("Contacts").click());
  const contacts = request.mock.calls.filter(([action]) => action === "contacts.list");
  expect(contacts).toHaveLength(1);
  expect(contacts[0][1]?.offset).toBe(0);
});

it("clears the selected conversation and page when switching sessions", async () => {
  request.mockImplementation(async (action, args) => action === "sessions.list" ? sessions :
    action === "chats.list" ? [{ id: "alice@c.us", name: args?.session_id === "one" ? "Alice" : "Bob" }] : []);
  await act(async () => root.render(<App />));
  await act(async () => container.querySelector<HTMLButtonElement>(".chat-row")!.click());
  expect(container.querySelector(".conversation")).not.toBeNull();
  await act(async () => container.querySelectorAll<HTMLButtonElement>(".session-row")[1].click());
  expect(container.querySelector(".conversation")).toBeNull();
  expect(container.querySelector(".chat-row")!.textContent).toContain("Bob");
});

it("keeps provider outage separate from account linking and blocks unavailable creation", async () => {
  request.mockRejectedValue(new Error("Gateway unavailable"));
  await act(async () => root.render(<App />));
  expect(container.textContent).toContain("Waiting for the gateway");
  expect(container.textContent).not.toContain("Link a session to see");
  expect(container.querySelector<HTMLButtonElement>('[aria-label="New session"]')!.disabled).toBe(true);
});
