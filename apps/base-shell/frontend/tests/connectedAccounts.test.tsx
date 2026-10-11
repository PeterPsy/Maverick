// @vitest-environment happy-dom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ConnectedAccountsDialog } from "../src/components/ConnectedAccountsDialog";
import { LoginScreen } from "../src/components/LoginScreen";
import { googleCallbackMessage } from "../src/components/GoogleServices";

const api = vi.hoisted(() => ({ connectedAccounts: vi.fn(), disconnectConnectedAccount: vi.fn(), selectConnectedAccount: vi.fn(),
  setConnectedAppAccess: vi.fn(), startGoogle: vi.fn(), googleStatus: vi.fn(), login: vi.fn() }));
vi.mock("../src/api", () => api);
vi.mock("../src/components/LoginPaperBackground", () => ({ LoginPaperBackground: () => <div /> }));
const data = {
  items: [{ account_id: "google-1", provider: "google", email: "alice@example.com", display_name: "Alice", status: "connected", services: ["calendar"] }],
  selection: { account_id: "google-1", disabled_apps: [] },
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
  afterEach(() => { act(() => root.unmount()); container.remove(); vi.restoreAllMocks(); vi.clearAllMocks(); });
  const button = (label: string) => [...container.querySelectorAll("button")].find(item => item.textContent === label)!;

  it("keeps Google services optional and submits precisely the chosen services", async () => {
    await act(async () => root.render(<LoginScreen onAuthenticated={vi.fn()} />));
    await act(async () => container.querySelectorAll<HTMLInputElement>('input[type="checkbox"]')[1].click());
    await act(async () => button("Continue with Google").click());
    expect(api.startGoogle).toHaveBeenCalledWith("login", ["gmail"]);
    expect(api.login).not.toHaveBeenCalled();
  });

  it("does not offer a working Google button when server configuration is missing", async () => {
    api.googleStatus.mockResolvedValue({ ...data.google, configured: false });
    await act(async () => root.render(<LoginScreen onAuthenticated={vi.fn()} />));
    expect(button("Continue with Google").disabled).toBe(true);
    expect(container.textContent).toContain("not configured");
  });

  it("explains missing consent while allowing independent app access changes", async () => {
    await act(async () => root.render(<ConnectedAccountsDialog onClose={vi.fn()} onChanged={changed} />));
    expect(container.querySelector("dialog")?.open).toBe(true);
    expect(container.textContent).toContain("Additional consent needed: gmail");
    await act(async () => container.querySelector<HTMLInputElement>('[aria-label="Allow Calendar to use Google"]')!.click());
    expect(api.setConnectedAppAccess).toHaveBeenCalledWith("calendar", false);
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
});
