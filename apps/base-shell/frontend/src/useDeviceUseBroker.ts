import { useLayoutEffect } from "react";
import type { MaverickFrameScope } from "./iframePolicy";
import { DeviceUseBroker } from "./deviceUseBroker";

export function useDeviceUseBroker(scope: MaverickFrameScope | null): void {
  useLayoutEffect(() => {
    if (!scope) return;
    const broker = new DeviceUseBroker(scope);
    window.addEventListener("message", broker.handle);
    return () => { window.removeEventListener("message", broker.handle); broker.dispose(); };
  }, [scope]);
}
