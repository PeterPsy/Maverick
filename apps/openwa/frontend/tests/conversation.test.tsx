import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { Conversation } from "../src/Conversation";
import { ResourcePanel } from "../src/ResourcePanels";
import { sendAttemptKey } from "../src/sendAttempts";
import { BackendError, callBackend, operation } from "../src/api";

vi.mock("../src/api", async (original) => ({ ...await original(), operation: vi.fn() }));
vi.mock("@maverick/pwa-cache", () => ({
  maverickAppIsVisible: () => true,
  observeMaverickVisibility: (listener: (visible: boolean) => void) => { listener(true); return () => {}; },
}));

const props = { session: { id: "session-1", name: "Phone", status: "ready" },
  chat: { id: "123@c.us", name: "Alice" }, canSend: true, sendScope: "scope-a", onBack: () => {} };
const key = sendAttemptKey(props.sendScope, props.session.id, props.chat.id);
const request = vi.mocked(operation);
let container: HTMLDivElement;
let root: Root;

async function render(scope = props.sendScope) {
  await act(async () => root.render(<Conversation {...props} sendScope={scope} />));
}
async function reopen(scope = props.sendScope) {
  await act(async () => root.unmount());
  root = createRoot(container);
  await render(scope);
}
async function compose(text = "  Hello\n") {
  const textarea = container.querySelector("textarea")!;
  await act(async () => {
    // Use the native setter so React sees a user edit rather than its own value tracker.
    Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, "value")!.set!.call(textarea, text);
    textarea.dispatchEvent(new Event("input", { bubbles: true }));
  });
}
async function submit() {
  await act(async () => { container.querySelector("form")!.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true })); });
}
async function click(text: string) {
  const button = [...container.querySelectorAll("button")].find((node) => node.textContent === text)!;
  expect(button).toBeDefined();
  await act(async () => button.click());
}
function sends() { return request.mock.calls.filter(([action]) => action === "messages.send" || action === "messages.reply"); }

beforeEach(() => {
  (globalThis as Record<string, unknown>).IS_REACT_ACT_ENVIRONMENT = true;
  localStorage.clear();
  vi.useFakeTimers();
  request.mockReset().mockResolvedValue([]);
  container = document.createElement("div");
  document.body.append(container);
  root = createRoot(container);
});
afterEach(async () => {
  await act(async () => root.unmount());
  container.remove();
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

describe("durable send attempts", () => {
  it.each(["success", "timeout"])("shows progress without a recovery alert until the send settles with %s", async (outcome) => {
    let complete!: (data: unknown) => void;
    let fail!: (error: Error) => void;
    request.mockImplementation((action) => action === "messages.send"
      ? new Promise((resolve, reject) => { complete = resolve; fail = reject; }) : Promise.resolve([]));
    await render(); await compose("Sending normally"); await submit();
    const saved = JSON.parse(localStorage.getItem(key)!);
    expect(saved.text).toBe("Sending normally");
    expect(container.querySelector(".send-warning")).toBeNull();
    const button = container.querySelector<HTMLButtonElement>('[aria-label="Send message"]')!;
    expect(button.textContent).toBe("Sending…");
    expect(button.disabled).toBe(true);
    await act(async () => {
      if (outcome === "success") complete({ id: "sent" });
      else fail(new BackendError("The request timed out. Check the conversation before retrying.", 504, "request_timeout"));
    });
    expect(sends()).toHaveLength(1);
    if (outcome === "success") {
      expect(container.querySelector(".send-warning")).toBeNull();
      expect(localStorage.getItem(key)).toBeNull();
      expect(container.querySelector("textarea")!.value).toBe("");
    } else {
      expect(container.querySelector(".send-warning")!.textContent).toContain("The request timed out");
      expect(JSON.parse(localStorage.getItem(key)!).key).toBe(saved.key);
    }
  });

  it("hides the previous failure during an active retry and keeps its original key", async () => {
    localStorage.setItem(key, JSON.stringify({ text: "Retry me", key: "request-abcdefghijkl", createdAt: Date.now(),
      state: "retryable", error: "Previous failure", status: 503, code: "gateway_unavailable" }));
    let complete!: (data: unknown) => void;
    request.mockImplementation((action) => action === "messages.send"
      ? new Promise((resolve) => { complete = resolve; }) : Promise.resolve([]));
    await render();
    expect(container.querySelector(".send-warning")!.textContent).toContain("Previous failure");
    await submit();
    expect(container.querySelector(".send-warning")).toBeNull();
    expect(JSON.parse(localStorage.getItem(key)!).error).not.toContain("Previous failure");
    expect(JSON.parse(localStorage.getItem(key)!)).not.toHaveProperty("status");
    expect(sends()[0][1]?.idempotency_key).toBe("request-abcdefghijkl");
    await act(async () => complete({ id: "sent" }));
    expect(localStorage.getItem(key)).toBeNull();
  });

  it("keeps a refused send's text and key without presenting uncertain-delivery recovery", async () => {
    request.mockImplementation(async (action) => {
      if (action === "messages.send") throw new BackendError("Send allowance reached", 429, "SEND_PACING_LIMITED");
      return [];
    });
    await render(); await compose("Not dispatched"); await submit();
    const saved = JSON.parse(localStorage.getItem(key)!);
    expect(saved).toMatchObject({ text: "Not dispatched", status: 429, code: "SEND_PACING_LIMITED" });
    await reopen();
    expect(container.textContent).toContain("Your text is saved");
    expect(container.textContent).not.toContain("I found the message");
    expect(container.textContent).not.toContain("Prepare a new send");
    request.mockResolvedValue({ id: "sent" });
    await submit();
    expect(sends()[1][1]).toEqual(sends()[0][1]);
    expect(localStorage.getItem(key)).toBeNull();
  });

  it("recognises an existing rate-limit warning while retaining its original retry key", async () => {
    localStorage.setItem(key, JSON.stringify({ text: "Existing draft", key: "request-abcdefghijkl", createdAt: Date.now(),
      state: "retryable", error: "OpenWA is rate limiting requests. Try again later." }));
    await render();
    expect(container.textContent).toContain("Your text is saved");
    expect(container.textContent).not.toContain("I found the message");
    expect(container.textContent).not.toContain("Prepare a new send");
    expect(sends()).toHaveLength(0);
    expect(JSON.parse(localStorage.getItem(key)!).key).toBe("request-abcdefghijkl");
    await submit();
    expect(sends()[0][1]?.idempotency_key).toBe("request-abcdefghijkl");
  });

  it("saves before dispatch and restores the exact text and key after timeout and remount", async () => {
    request.mockImplementation(async (action, body) => {
      if (action === "messages.send") {
        expect(JSON.parse(localStorage.getItem(key)!).key).toBe(body!.idempotency_key);
        throw new BackendError("Delivery uncertain", 503, "gateway_unavailable");
      }
      return [];
    });
    await render(); await compose(); await submit();
    const first = sends()[0][1];
    expect(first?.text).toBe("  Hello\n");
    await reopen();
    expect(container.querySelector("textarea")!.value).toBe(first!.text);
    await submit();
    expect(sends()[1][1]).toEqual(first);
    expect(container.textContent).toContain("Delivery uncertain");
  });

  it("keeps send errors through successful polling and read failures", async () => {
    request.mockImplementation(async (action) => {
      if (action === "messages.send") throw new BackendError("Send timed out", 503, "gateway_unavailable");
      return [];
    });
    await render(); await compose("Hello"); await submit();
    await act(async () => { await vi.advanceTimersByTimeAsync(8000); });
    expect(container.textContent).toContain("Send timed out");
    request.mockRejectedValueOnce(new Error("Read failed"));
    await act(async () => { await vi.advanceTimersByTimeAsync(8000); });
    expect(container.textContent).toContain("Read failed");
    expect(container.textContent).toContain("Send timed out");
    await act(async () => { await vi.advanceTimersByTimeAsync(16000); });
    expect(container.textContent).not.toContain("Read failed");
    expect(container.textContent).toContain("Send timed out");
  });

  it.each(["success", "timeout"])("retains an in-flight attempt across navigation and settles %s after unmount", async (outcome) => {
    let complete!: (data: unknown) => void;
    let fail!: (error: Error) => void;
    request.mockImplementation((action) => action === "messages.send"
      ? new Promise((resolve, reject) => { complete = resolve; fail = reject; }) : Promise.resolve([]));
    await render(); await compose("In flight"); await submit();
    const original = sends()[0][1];
    await reopen();
    expect(container.querySelector("textarea")!.value).toBe("In flight");
    expect(JSON.parse(localStorage.getItem(key)!).key).toBe(original!.idempotency_key);
    await act(async () => {
      if (outcome === "success") complete({ id: "sent" });
      else fail(new Error("Timeout after navigation"));
    });
    await reopen();
    if (outcome === "success") {
      expect(localStorage.getItem(key)).toBeNull();
      expect(container.querySelector("textarea")!.value).toBe("");
    } else {
      request.mockRejectedValue(new Error("Still uncertain"));
      await submit();
      expect(sends()[1][1]).toEqual(original);
    }
  });

  it("restores replies with the same quote and prevents editing an unresolved payload", async () => {
    request.mockImplementation(async (action) => {
      if (action === "messages.reply") throw new Error("Network timeout");
      return [{ id: "quote", waMessageId: "wa-quote", body: "Original", direction: "incoming" }];
    });
    await render(); await click("Reply"); await compose("Reply text"); await submit();
    await reopen();
    expect(container.textContent).toContain("Original");
    expect(container.querySelector("textarea")!.readOnly).toBe(true);
    expect(container.querySelector<HTMLButtonElement>('[aria-label="Cancel reply"]')!.disabled).toBe(true);
    await submit();
    expect(sends()[1]).toEqual(sends()[0]);
    expect(sends()[0][1]?.message_id).toBe("wa-quote");
  });

  it("blocks unknown 409 retries and requires a deliberate recovery before issuing a new key", async () => {
    request.mockImplementation(async (action) => {
      if (action === "messages.send") throw new BackendError("Outcome unknown", 409, "IDEMPOTENCY_OUTCOME_UNKNOWN");
      return [];
    });
    await render(); await compose("Hello"); await submit();
    const firstKey = sends()[0][1]!.idempotency_key;
    await reopen(); await submit();
    expect(sends()).toHaveLength(1);
    expect(container.querySelector<HTMLButtonElement>('[aria-label="Send message"]')!.disabled).toBe(true);
    await click("Prepare a new send");
    expect(container.querySelector('[role="dialog"]')!.textContent).toContain("may have arrived");
    await click("Keep previous attempt"); await submit();
    expect(sends()).toHaveLength(1);
    await click("Prepare a new send"); await click("I checked: prepare a new send");
    expect(sends()).toHaveLength(1); // Preparing never sends automatically.
    await submit();
    expect(sends()[1][1]!.idempotency_key).not.toBe(firstKey);
  });

  it("retries an in-progress 409 with its existing key", async () => {
    request.mockImplementation(async (action) => {
      if (action === "messages.send") throw new BackendError("Still running", 409, "IDEMPOTENCY_KEY_IN_PROGRESS");
      return [];
    });
    await render(); await compose("Hello"); await submit(); await reopen();
    expect(container.textContent).not.toContain("Prepare a new send");
    await submit();
    expect(sends()[1][1]).toEqual(sends()[0][1]);
  });

  it("blocks stale retries before the provider expires the key", async () => {
    localStorage.setItem(key, JSON.stringify({ text: "Old send", key: "old-request-abcdefghijkl", createdAt: Date.now() - 24 * 3600000,
      state: "in_progress", error: "Still running" }));
    await render(); await submit();
    expect(sends()).toHaveLength(0);
    expect(container.textContent).toContain("send outcome is uncertain");
    expect(container.textContent).toContain("Prepare a new send");
  });

  it("isolates attempts by actor/workspace/gateway scope, session and chat", async () => {
    localStorage.setItem(key, JSON.stringify({ text: "Private draft", key: "request-abcdefghijkl", createdAt: Date.now(),
      state: "retryable", error: "Uncertain" }));
    await render("scope-b");
    expect(container.querySelector("textarea")!.value).toBe("");
    expect(sendAttemptKey("scope-a", "session-2", props.chat.id)).not.toBe(key);
    expect(sendAttemptKey("scope-a", props.session.id, "other@c.us")).not.toBe(key);
    await reopen();
    expect(container.querySelector("textarea")!.value).toBe("Private draft");
  });

  it("never sends when persistence fails or the saved attempt is invalid", async () => {
    await render(); await compose("Hello");
    const storage = localStorage;
    vi.stubGlobal("localStorage", { getItem: storage.getItem.bind(storage), removeItem: storage.removeItem.bind(storage),
      setItem: () => { throw new Error("Quota exceeded"); } });
    await submit();
    expect(sends()).toHaveLength(0);
    expect(container.textContent).toContain("could not be saved");
    vi.unstubAllGlobals();
    localStorage.setItem(key, "{broken");
    await reopen(); await compose("Hello"); await submit();
    expect(sends()).toHaveLength(0);
    expect(container.textContent).toContain("could not be read");
  });

  it("clears a confirmed send even if the following message refresh fails", async () => {
    await render(); await compose("Hello");
    request.mockImplementation(async (action) => {
      if (action === "messages.list") throw new Error("Refresh failed");
      return { id: "sent" };
    });
    await submit();
    expect(localStorage.getItem(key)).toBeNull();
    expect(container.querySelector("textarea")!.value).toBe("");
    expect(container.textContent).toContain("Refresh failed");
    await reopen();
    expect(container.textContent).not.toContain("Retry same send");
  });

  it("lets the user acknowledge an arrived message without sending again", async () => {
    localStorage.setItem(key, JSON.stringify({ text: "Arrived", key: "request-abcdefghijkl", createdAt: Date.now(),
      state: "unknown", error: "Check chat" }));
    await render(); await click("I found the message");
    expect(localStorage.getItem(key)).toBeNull();
    expect(container.querySelector("textarea")!.value).toBe("");
    expect(sends()).toHaveLength(0);
  });
});

it("retains the backend status and code for conflict recovery", async () => {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify({ error: "IDEMPOTENCY_OUTCOME_UNKNOWN", detail: "Check chat" }), { status: 409 })));
  await expect(callBackend({ action: "messages.send" })).rejects.toMatchObject({ status: 409, code: "IDEMPOTENCY_OUTCOME_UNKNOWN", message: "Check chat" });
});

it("renders provider string chat previews and falls back for missing or empty previews", async () => {
  await act(async () => root.render(<ResourcePanel session={props.session} tab="chats"
    chats={[{ id: "123@c.us", name: "Alice", lastMessage: "Provider preview" }, { id: "empty@c.us", lastMessage: "" }, { id: "missing@c.us" }]}
    records={[]} search="" loading={false} page={0} more={false} onPage={() => {}} onManage={() => {}}
    onTab={() => {}} onSearch={() => {}} onChat={() => {}} />));
  expect([...container.querySelectorAll(".chat-description small")].map((node) => node.textContent)).toEqual(["Provider preview", "empty@c.us", "missing@c.us"]);
});

it("does not overlap slow message polls and drops a cancelled page response", async () => {
  const firstPage = Array.from({ length: 50 }, (_, index) => ({ id: String(index), body: "Recent message " + index }));
  request.mockResolvedValueOnce(firstPage);
  await render();
  let finish!: (data: unknown) => void;
  request.mockImplementationOnce(() => new Promise((resolve) => { finish = resolve; }));
  await act(async () => { await vi.advanceTimersByTimeAsync(24000); });
  expect(request).toHaveBeenCalledTimes(2);
  const signal = request.mock.calls[1][2]!;
  request.mockResolvedValueOnce([{ id: "older", body: "Older page" }]);
  await click("Older messages");
  expect(signal.aborted).toBe(true);
  expect(container.textContent).toContain("Older page");
  expect(container.textContent).not.toContain("Recent message");
  await act(async () => finish([{ id: "stale", body: "Stale page" }]));
  expect(container.textContent).not.toContain("Stale page");
});

it("stops message reads when the session loses readiness", async () => {
  await render();
  request.mockClear();
  await act(async () => root.render(<Conversation {...props} session={{ ...props.session, status: "disconnected" }} />));
  await act(async () => { await vi.advanceTimersByTimeAsync(24000); });
  expect(request).not.toHaveBeenCalled();
  expect(container.textContent).toContain("session is not ready");
});

it("blocks repeated submit events before React renders the busy state", async () => {
  let finish!: (data: unknown) => void;
  request.mockImplementation((action) => action === "messages.send"
    ? new Promise((resolve) => { finish = resolve; }) : Promise.resolve([]));
  await render(); await compose("One send");
  await act(async () => {
    const form = container.querySelector("form")!;
    form.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }));
    form.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }));
  });
  expect(sends()).toHaveLength(1);
  await act(async () => finish({ id: "sent" }));
});

it("returns to the newest page after a confirmed send even if the user paged during dispatch", async () => {
  const pageRows = Array.from({ length: 50 }, (_, index) => ({ id: String(index), body: "Recent message " + index }));
  let finish!: (data: unknown) => void;
  request.mockImplementation((action) => action === "messages.send"
    ? new Promise((resolve) => { finish = resolve; }) : Promise.resolve(pageRows));
  await render(); await compose("Hello"); await submit();
  await click("Older messages");
  expect(request.mock.calls.at(-1)![1]?.offset).toBe(50);
  await act(async () => finish({ id: "sent" }));
  expect(request.mock.calls.at(-1)![1]?.offset).toBe(0);
  expect(container.querySelector("textarea")!.value).toBe("");
});

it("explains a search with no matches and exposes the current resource selection", async () => {
  await act(async () => root.render(<ResourcePanel session={props.session} tab="chats"
    chats={[{ id: "123@c.us", name: "Alice" }]} records={[]} search="Bob" loading={false} page={0} more={false}
    onPage={() => {}} onManage={() => {}} onTab={() => {}} onSearch={() => {}} onChat={() => {}} />));
  expect(container.textContent).toContain("No matches on this page");
  expect([...container.querySelectorAll('button[aria-pressed="true"]')].map((button) => button.textContent)).toEqual(["Chats"]);
});
