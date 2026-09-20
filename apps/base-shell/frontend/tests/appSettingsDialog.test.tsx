// @vitest-environment happy-dom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { AppRegistryItem } from "../src/api";
import { AppSettingsDialog, externalSettingsProvider } from "../src/components/AppSettingsDialog";

const widget = vi.fn((props: Record<string, unknown>) => <div data-widget-kind={String(props.contentKind)} />);
vi.mock("../src/components/WidgetSlot", () => ({ WidgetSlot: (props: Record<string, unknown>) => widget(props) }));

const app = { app_id: "website-studio", name: "Website Studio", description: "Build websites", version: "1", publisher: "Maverick", frontend_role: "workspace", provides: [], logo: null } as unknown as AppRegistryItem;
const provider = { ...app, app_id: "publisher-renamed", provides: [{ interface: "external.surfaces.settings", version: "1", surfaces: ["view"] }] } as AppRegistryItem;
const frameScope = { workspaceId: "tenant-a", sessionGeneration: "session-a" };
const theme = { color_scheme: "dark", effective: "dark", mode: "dark" } as const;

describe("Per-app settings", () => {
  let container: HTMLDivElement;
  let root: Root;
  const close = vi.fn();
  const pin = vi.fn();
  const openApp = vi.fn();
  beforeEach(() => {
    (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
    container = document.createElement("div"); document.body.append(container); root = createRoot(container);
    vi.spyOn(HTMLDialogElement.prototype, "showModal").mockImplementation(function (this: HTMLDialogElement) { this.open = true; });
    vi.spyOn(HTMLDialogElement.prototype, "close").mockImplementation(function (this: HTMLDialogElement) { this.open = false; });
    pin.mockResolvedValue(undefined);
  });
  afterEach(() => { act(() => root.unmount()); container.remove(); vi.restoreAllMocks(); vi.clearAllMocks(); });
  async function render(apps = [app, provider], last = false) {
    await act(async () => root.render(<AppSettingsDialog app={app} apps={apps} frameScope={frameScope} isPinned isLastPinned={last} onClose={close} onOpenApp={openApp} onTogglePin={pin} shellTheme={theme} />));
  }
  async function external() {
    await act(async () => [...container.querySelectorAll("button")].find(button => button.textContent === "Superfici esterne")!.click());
  }
  it("resolves a unique capability provider without coupling to its id", () => {
    expect(externalSettingsProvider([app, provider])?.app_id).toBe("publisher-renamed");
    expect(externalSettingsProvider([app])).toBeNull();
    expect(externalSettingsProvider([provider, { ...provider, app_id: "duplicate" }])).toBeNull();
    expect(externalSettingsProvider([{ ...provider, provides: [{ ...provider.provides[0], version: "2" }] }])).toBeNull();
  });
  it("prefers the selected app's own surface without hijacking other apps", () => {
    const owner = { ...app, provides: [{ interface: "app.external.surfaces.settings", version: "1", description: "Own surfaces", surfaces: ["widget"] }] };
    expect(externalSettingsProvider([owner, provider], owner)).toBe(owner);
    expect(externalSettingsProvider([owner, provider], app)).toBe(provider);
    expect(externalSettingsProvider([owner], app)).toBeNull();
  });
  it("opens a native modal with exact app-owned settings and scoped external context", async () => {
    await render();
    expect(container.querySelector("dialog")?.open).toBe(true);
    expect(widget).toHaveBeenLastCalledWith(expect.objectContaining({ contentKind: "shell.app.settings", preferredOwnerAppId: app.app_id, activeWorkspaceId: "tenant-a", frameScope }));
    await external();
    expect(widget).toHaveBeenLastCalledWith(expect.objectContaining({ contentKind: "shell.app.external.surfaces", preferredOwnerAppId: provider.app_id, content: { app_id: app.app_id, app_name: app.name } }));
    await act(async () => container.querySelector("dialog")!.dispatchEvent(new Event("cancel", { cancelable: true })));
    expect(close).toHaveBeenCalledOnce();
    expect(HTMLDialogElement.prototype.close).toHaveBeenCalledOnce();
    expect(container.querySelector("dialog")?.open).toBe(false);
  });
  it("shows an honest unavailable state when the external provider is absent", async () => {
    await render([app]); await external();
    expect(container.textContent).toContain("Nessun gestore univoco");
    expect(container.querySelector("[data-widget-kind]")).toBeNull();
  });
  it("surfaces pin failures and protects the last rail entry", async () => {
    pin.mockRejectedValue(new Error("Salvataggio non riuscito"));
    await render();
    await act(async () => container.querySelector<HTMLInputElement>("input")!.click());
    expect(pin).toHaveBeenCalledOnce();
    expect(container.querySelector('[role="alert"]')?.textContent).toBe("Salvataggio non riuscito");
    await render([app, provider], true);
    expect(container.querySelector<HTMLInputElement>("input")!.disabled).toBe(true);
    expect(container.textContent).toContain("Mantieni almeno un’app");
  });
});
