/** @vitest-environment happy-dom */
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { NativeDeviceUseSnapshot } from "../lib/deviceUse";
import { DeviceUseControl } from "./DeviceUseControl";

const snapshot: NativeDeviceUseSnapshot = {
  available: true,
  active: false,
  activationId: null,
  mode: "off",
  phase: "idle",
  notice: "",
  apps: [
    { bundleId: "com.apple.Notes", name: "Note" },
    { bundleId: "com.apple.TextEdit", name: "TextEdit" },
  ],
  permissions: { screen: true, accessibility: false, input: true },
  settings: { selectedApp: "com.apple.Notes", additionalApps: [], consentMode: "perAction" },
};

let root: Root | null = null;
afterEach(() => { act(() => root?.unmount()); root = null; document.body.innerHTML = ""; });

describe("Device Use control", () => {
  it("exposes the three modes and the full authority contract", async () => {
    const host = document.createElement("div"); document.body.append(host);
    root = createRoot(host);
    const onModeChange = vi.fn();
    await act(async () => {
      root?.render(<DeviceUseControl
        busy={false}
        locked={false}
        mode="full"
        onConfigure={async () => undefined}
        onModeChange={onModeChange}
        onRefresh={async () => snapshot}
        onRequestPermission={() => undefined}
        snapshot={{ ...snapshot, active: true, mode: "full", phase: "ready" }}
      />);
    });
    const control = host.querySelector(".chatapp-device-use-control");
    const modes = [...host.querySelectorAll('[role="radio"]')];
    expect(control?.className).toBe("chatapp-device-use-control");
    expect(modes.map((item) => item.textContent)).toEqual(["Off", "On", "Full"]);
    expect(modes.find((item) => item.getAttribute("aria-checked") === "true")?.textContent).toBe("Full");
    await act(async () => { (host.querySelector('[aria-label="Apri impostazioni Device Use"]') as HTMLButtonElement).click(); });
    expect(document.body.textContent).toContain("Solo Off/Stop e il blocco schermo revocano l'autorità");
    expect([...document.body.querySelectorAll('.chatapp-device-use-modal__radios input')].map((item) => item.parentElement?.textContent)).toEqual(["Ogni azione", "Una per incarico"]);
    await act(async () => { (host.querySelector('[role="radio"]') as HTMLButtonElement).click(); });
    expect(onModeChange).toHaveBeenCalledWith("off");
  });
});
