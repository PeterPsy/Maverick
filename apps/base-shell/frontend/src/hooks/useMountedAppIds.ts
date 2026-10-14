import { useMemo, useSyncExternalStore } from "react";
import {
  loopinoFrameRegistryRevision,
  registeredLoopinoAppIds,
  subscribeLoopinoFrameRegistry,
  type LoopinoFrameScope,
} from "../iframePolicy";

/** Include main views and app-owned widgets, within the authenticated scope. */
export function useMountedAppIds(scope: LoopinoFrameScope | null): string[] {
  const revision = useSyncExternalStore(subscribeLoopinoFrameRegistry, loopinoFrameRegistryRevision);
  return useMemo(() => scope ? registeredLoopinoAppIds(scope) : [], [revision, scope]);
}
