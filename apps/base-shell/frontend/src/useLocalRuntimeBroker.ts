import { useLayoutEffect } from "react";
import type { MaverickFrameScope } from "./iframePolicy";
import { LocalRuntimeBroker } from "./localRuntimeBroker";

export function useLocalRuntimeBroker(scope: MaverickFrameScope | null): void {
  useLayoutEffect(() => {
    if (!scope) return;
    const broker = new LocalRuntimeBroker(scope);
    window.addEventListener("message", broker.handle);
    return () => { window.removeEventListener("message", broker.handle); broker.dispose(); };
  }, [scope]);
}
