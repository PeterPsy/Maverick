import { useMemo, useSyncExternalStore } from "react";
import {
  maverickFrameRegistryRevision,
  registeredMaverickAppIds,
  subscribeMaverickFrameRegistry,
  type MaverickFrameScope,
} from "../iframePolicy";

/** Include main views and app-owned widgets, within the authenticated scope. */
export function useMountedAppIds(scope: MaverickFrameScope | null): string[] {
  const revision = useSyncExternalStore(subscribeMaverickFrameRegistry, maverickFrameRegistryRevision);
  return useMemo(() => scope ? registeredMaverickAppIds(scope) : [], [revision, scope]);
}
