// @vitest-environment happy-dom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ConnectedAccountsDialog } from "../src/components/ConnectedAccountsDialog";
import { LoginScreen } from "../src/components/LoginScreen";
import { googleCallbackMessage } from "../src/components/GoogleServices";

const api = vi.hoisted(() => ({ connectedAccounts: vi.fn(), disconnectConnectedAccount: vi.fn(), selectConnectedAccount: vi.fn(),
  setConnectedAppAccess: vi.fn(), setConnectedWorkspaceAccess: vi.fn(), startGoogle: vi.fn(), googleStatus: vi.fn(), login: vi.fn(), getSession: vi.fn() }));
vi.mock("../src/api", () => api);
vi.mock("../src/components/LoginPaperBackground", () => ({ LoginPaperBackground: () => <div /> }));
const data = {
  workspace_id: "default",
  items: [{ account_id: "google-1", provider: "google", email: "alice@example.com", display_name: "Alice", status: "connected", services: ["calendar"] }],
  selection: { account_id: "google-1", account_ids: ["google-1"], disabled_apps: [] },
  apps: [{ app_id: "calendar", name: "Calendar", services: ["calendar"] }, { app_id: "mail", name: "Mail", services: ["gmail"] }],
  google: { configured: true, registration_enabled: true, services: [] },
};

describe("Google login and connected accounts", () => {
  let container: HTMLDivElement;
  let root: Root;
  const changed = vi.fn();
  beforeEach(() => {
    (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
    container = document.createElement("div"); document.body.append(container); root = createRoot(container);
    vi.spyOn(HTMLDialogElement.prototype, "showModal").mockImplementation(function (this: HTMLDialogElement) { this.open = true; });
    vi.spyOn(HTMLDialogElement.prototype, "close").mockImplementation(function (this: HTMLDialogElement) { this.open = false; });
    api.connectedAccounts.mockResolvedValue(data);
    api.googleStatus.mockResolvedValue(data.google);
    api.startGoogle.mockResolvedValue(undefined);
    api.setConnectedAppAccess.mockResolvedValue({ status: "updated" });
    api.disconnectConnectedAccount.mockResolvedValue({ status: "disconnected", revoked_at_google: true });
  });
  afterEach(() => { act(() => root.unmount()); container.remove(); vi.restoreAllMocks(); vi.clearAllMocks(); vi.unstubAllGlobals(); });
  const button = (label: string) => [...container.querySelectorAll("button")].find(item => item.textContent === label)!;

  it("keeps Google services optional and submits precisely the chosen services", async () => {
    await act(async () => root.render(<LoginScreen onAuthenticated={vi.fn()} />));
    await act(async () => container.querySelectorAll<HTMLInputElement>('input[type="checkbox"]')[1].click());
    await act(async () => button("Continue with Google").click());
    expect(api.startGoogle).toHaveBeenCalledWith("login", ["gmail"], expect.any(AbortSignal));
    expect(api.login).not.toHaveBeenCalled();
  });

  it("does not offer a working Google button when server configuration is missing", async () => {
    api.googleStatus.mockResolvedValue({ ...data.google, configured: false });
    await act(async () => root.render(<LoginScreen onAuthenticated={vi.fn()} />));
    expect(button("Continue with Google").disabled).toBe(true);
    expect(container.textContent).toContain("not configured");
  });

  it("explains missing consent while allowing independent app access changes", async () => {
    await act(async () => root.render(<ConnectedAccountsDialog initialSection="access" onClose={vi.fn()} onChanged={changed} />));
    expect(container.querySelector("dialog")?.open).toBe(true);
    expect(container.textContent).toContain("Additional consent needed: gmail");
    await act(async () => container.querySelector<HTMLInputElement>('[aria-label="Allow Calendar to use Google"]')!.click());
    expect(api.setConnectedAppAccess).toHaveBeenCalledWith("default", "calendar", false);
    expect(changed).toHaveBeenCalledOnce();
    expect(api.disconnectConnectedAccount).not.toHaveBeenCalled();
  });

  it("requires an explicit disconnect action and preserves a provider-revocation failure message", async () => {
    api.disconnectConnectedAccount.mockResolvedValue({ status: "disconnected", revoked_at_google: false });
    await act(async () => root.render(<ConnectedAccountsDialog onClose={vi.fn()} onChanged={changed} />));
    await act(async () => button("Disconnect").click());
    expect(api.disconnectConnectedAccount).not.toHaveBeenCalled();
    await act(async () => button("Disconnect Google").click());
    expect(api.disconnectConnectedAccount).toHaveBeenCalledWith("google-1");
    expect(container.textContent).toContain("Revocation at Google could not be confirmed");
  });

  it("turns callback codes into actionable messages without displaying untrusted text", () => {
    expect(googleCallbackMessage("google_workspace_pending")).toContain("assign you a workspace");
    expect(googleCallbackMessage("google_account_link_required")).toContain("password first");
    expect(googleCallbackMessage("<script>untrusted</script>")).not.toContain("untrusted");
  });

  it("refreshes native accounts and releases the connecting button after browser consent", async () => {
    api.startGoogle.mockResolvedValue("completed");
    await act(async () => root.render(<ConnectedAccountsDialog onClose={vi.fn()} onChanged={changed} />));
    await act(async () => button("Update permissions or add an account").click());
    expect(changed).toHaveBeenCalledOnce();
    expect(api.connectedAccounts).toHaveBeenCalledTimes(2);
    expect(container.textContent).toContain("Google connected.");
    expect(button("Update permissions or add an account").disabled).toBe(false);
  });

  it("finishes native Google login using the session saved in the webview", async () => {
    const session = { authenticated: true, user: { username: "alice" }, workspace_id: "default" };
    const authenticated = vi.fn();
    api.startGoogle.mockResolvedValue("completed"); api.getSession.mockResolvedValue(session);
    await act(async () => root.render(<LoginScreen onAuthenticated={authenticated} />));
    await act(async () => button("Continue with Google").click());
    expect(authenticated).toHaveBeenCalledExactlyOnceWith(session);
    expect(button("Continue with Google").disabled).toBe(false);
  });

  it("allows cancellation while the system browser is open and stops polling on unmount", async () => {
    api.startGoogle.mockImplementation(() => new Promise(() => {}));
    await act(async () => root.render(<ConnectedAccountsDialog onClose={vi.fn()} onChanged={changed} />));
    await act(async () => button("Update permissions or add an account").click());
    const signal = api.startGoogle.mock.calls[0][2] as AbortSignal;
    expect(container.textContent).toContain("Maverick will update automatically");
    await act(async () => button("Cancel connection").click());
    expect(signal.aborted).toBe(true);
    expect(button("Update permissions or add an account").disabled).toBe(false);
  });

  it("restores an ordinary browser panel when returning through the back button", async () => {
    api.startGoogle.mockResolvedValue("redirecting");
    await act(async () => root.render(<ConnectedAccountsDialog onClose={vi.fn()} onChanged={changed} />));
    await act(async () => button("Update permissions or add an account").click());
    expect(button("Connecting…").disabled).toBe(true);
    const event = new Event("pageshow"); Object.defineProperty(event, "persisted", { value: true });
    await act(async () => window.dispatchEvent(event));
    expect(button("Update permissions or add an account").disabled).toBe(false);
  });

  it("releases Google and logout controls when an offline server switch cancels consent", async () => {
    const postMessage = vi.fn().mockImplementation(async ({ action }: { action: string }) => {
      if (action === "switch") throw new Error("Server unavailable");
      return { profiles: [
        { id: "current", name: "Current", origin: "https://current.example", current: true },
        { id: "offline", name: "Offline", origin: "https://offline.example", current: false },
      ] };
    });
    vi.stubGlobal("webkit", { messageHandlers: { maverickServers: { postMessage } } });
    api.startGoogle.mockImplementation((_mode, _services, signal: AbortSignal) => new Promise((_resolve, reject) => {
      signal.addEventListener("abort", () => reject(new DOMException("Aborted", "AbortError")), { once: true });
    }));
    await act(async () => root.render(<ConnectedAccountsDialog initialSection="google" onClose={vi.fn()} onChanged={changed} onLogout={vi.fn()} />));
    await act(async () => button("Update permissions or add an account").click());
    await act(async () => button("dnsServers").click());
    await act(async () => button("Switch server").click());
    expect(container.textContent).toContain("Server unavailable");
    await act(async () => button("linkConnected accounts").click());
    expect(container.querySelector<HTMLButtonElement>(".bs-google-button")!.disabled).toBe(false);
    expect(container.textContent).not.toContain("Continue in your browser");
    await act(async () => button("logoutLog out").click());
    expect(button("Log out of this server").disabled).toBe(false);
    expect(api.startGoogle.mock.calls[0][2].aborted).toBe(true);
  });

  it("ignores a cancelled flow completing after another connection has started", async () => {
    let completeFirst!: (result: string) => void;
    let completeSecond!: (result: string) => void;
    api.startGoogle.mockImplementationOnce(() => new Promise(resolve => { completeFirst = resolve; }))
      .mockImplementationOnce(() => new Promise(resolve => { completeSecond = resolve; }));
    await act(async () => root.render(<ConnectedAccountsDialog initialSection="google" onClose={vi.fn()} onChanged={changed} />));
    await act(async () => button("Update permissions or add an account").click());
    await act(async () => button("Cancel connection").click());
    await act(async () => button("Update permissions or add an account").click());
    await act(async () => completeFirst("completed"));
    expect(changed).not.toHaveBeenCalled();
    expect(button("Connecting…").disabled).toBe(true);
    await act(async () => completeSecond("completed"));
    expect(changed).toHaveBeenCalledOnce();
    expect(button("Update permissions or add an account").disabled).toBe(false);
  });
});
