// @vitest-environment happy-dom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ConnectedAccountsDialog } from "./ConnectedAccountsDialog";
import type { ConnectedAccountsPayload } from "../api";

const api = vi.hoisted(() => ({ connectedAccounts: vi.fn(), setConnectedWorkspaceAccess: vi.fn(), selectConnectedAccount: vi.fn(),
  disconnectConnectedAccount: vi.fn(), setConnectedAppAccess: vi.fn(), startGoogle: vi.fn() }));
vi.mock("../api", () => api);

let host: HTMLDivElement;
let root: Root;
let data: ConnectedAccountsPayload;
const changed = vi.fn();
const flush = () => act(async () => { await Promise.resolve(); });
const render = async () => {
  await act(async () => { root.render(<ConnectedAccountsDialog onClose={vi.fn()} onChanged={changed} />); });
  await flush();
};
const checkbox = (email: string) => host.querySelector<HTMLInputElement>(`input[aria-label="Use ${email} in this workspace"]`)!;

beforeEach(() => {
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
  vi.clearAllMocks();
  Object.defineProperties(HTMLDialogElement.prototype, {
    showModal: { configurable: true, value: vi.fn() }, close: { configurable: true, value: vi.fn() },
  });
  data = {
    workspace_id: "default",
    items: [{ account_id: "google_a", provider: "google", email: "a@example.com", display_name: "A", status: "connected", services: ["gmail"] },
      { account_id: "google_b", provider: "google", email: "b@example.com", display_name: "B", status: "connected", services: ["calendar"] }],
    selection: { account_id: "google_a", account_ids: ["google_a"], disabled_apps: [] },
    apps: [{ app_id: "calendar", name: "Calendar", services: ["calendar"] }],
    google: { configured: true, registration_enabled: true, services: [] },
  };
  api.connectedAccounts.mockImplementation(async () => structuredClone(data));
  api.setConnectedWorkspaceAccess.mockImplementation(async (_workspace: string, id: string, enabled: boolean) => {
    data.selection!.account_ids = enabled ? [...data.selection!.account_ids, id] : data.selection!.account_ids.filter(item => item !== id);
    return { status: "updated" };
  });
  host = document.createElement("div"); document.body.append(host); root = createRoot(host);
});
afterEach(async () => { await act(async () => root.unmount()); host.remove(); });

describe("workspace Google account selection", () => {
  it("adds another account without replacing the workspace default", async () => {
    await render();
    expect(checkbox("a@example.com").checked).toBe(true);
    expect(checkbox("b@example.com").checked).toBe(false);
    await act(async () => checkbox("b@example.com").click()); await flush();
    expect(api.setConnectedWorkspaceAccess).toHaveBeenCalledWith("default", "google_b", true);
    expect(api.selectConnectedAccount).not.toHaveBeenCalled();
    expect(checkbox("a@example.com").checked).toBe(true);
    expect(checkbox("b@example.com").checked).toBe(true);
    expect(host.textContent).toContain("1 account available · calendar");
  });

  it("removes workspace access separately from global Google disconnect", async () => {
    await render();
    await act(async () => checkbox("a@example.com").click()); await flush();
    expect(api.setConnectedWorkspaceAccess).toHaveBeenCalledWith("default", "google_a", false);
    expect(api.disconnectConnectedAccount).not.toHaveBeenCalled();
    expect(changed).toHaveBeenCalled();
  });

  it("offers Make default only for enabled accounts and changes it explicitly", async () => {
    data.selection!.account_ids.push("google_b");
    api.selectConnectedAccount.mockImplementation(async (_workspace: string, id: string) => { data.selection!.account_id = id; });
    await render();
    const button = Array.from(host.querySelectorAll("button")).find(item => item.textContent === "Make default")!;
    await act(async () => button.click()); await flush();
    expect(api.selectConnectedAccount).toHaveBeenCalledWith("default", "google_b");
    expect(api.setConnectedWorkspaceAccess).not.toHaveBeenCalled();
    expect(checkbox("a@example.com").checked).toBe(true);
    expect(checkbox("b@example.com").checked).toBe(true);
  });

  it("reloads a different workspace selection when reopened", async () => {
    await render();
    await act(async () => root.unmount()); root = createRoot(host);
    data.selection = { account_id: "google_b", account_ids: ["google_b"], disabled_apps: [] };
    data.workspace_id = "second";
    await render();
    expect(checkbox("a@example.com").checked).toBe(false);
    expect(checkbox("b@example.com").checked).toBe(true);
  });
});
