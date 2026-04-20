import { useEffect, useRef, useState } from "react";
import { AppRegistryItem } from "../api";

type AppFrameParams = Record<string, string | boolean | null>;
type AppReadyMessage = {
  app_id?: string;
  deleted_thread_id?: string;
  owner_app_id?: string;
  params?: Record<string, string | boolean | null>;
  resource?: string;
  type?: string;
  workspace_id?: string;
};

export function AppFrameHost({
  activeApp,
  activeAppParams,
  activeWorkspaceId,
  onOpenApp,
}: {
  activeApp: AppRegistryItem;
  activeAppParams: AppFrameParams;
  activeWorkspaceId: string;
  onOpenApp: (appId: string, params?: AppFrameParams) => void;
}) {
  const [mountedApps, setMountedApps] = useState<Array<{ app: AppRegistryItem; mountKey: string }>>([
    { app: activeApp, mountKey: `${activeWorkspaceId}:${activeApp.app_id}` },
  ]);
  const frameRefs = useRef<Record<string, HTMLIFrameElement | null>>({});
  const latestNavigationRef = useRef<{ appId: string; params: AppFrameParams }>({
    appId: activeApp.app_id,
    params: activeAppParams,
  });
  const paramsSignature = JSON.stringify(activeAppParams);

  useEffect(() => {
    setMountedApps((current) => {
      const nextKey = `${activeWorkspaceId}:${activeApp.app_id}`;
      const workspaceMountedApps = current.filter((item) => item.mountKey.startsWith(`${activeWorkspaceId}:`));
      if (workspaceMountedApps.some((item) => item.mountKey === nextKey)) {
        return workspaceMountedApps;
      }
      return [...workspaceMountedApps, { app: activeApp, mountKey: nextKey }];
    });
  }, [activeApp, activeWorkspaceId]);

  useEffect(() => {
    latestNavigationRef.current = { appId: activeApp.app_id, params: activeAppParams };
    postNavigation(frameRefs.current[activeApp.app_id], activeApp.app_id, activeAppParams);
  }, [activeApp.app_id, paramsSignature]);

  useEffect(() => {
    function handleAppMessage(event: MessageEvent) {
      if (event.origin !== window.location.origin || !event.data || typeof event.data !== "object") {
        return;
      }
      const payload = event.data as AppReadyMessage;
      if (!payload.type) {
        return;
      }
      if (payload.type === "maverick.app.data-changed" && payload.owner_app_id) {
        const ownerFrame = frameRefs.current[payload.owner_app_id];
        if (ownerFrame?.contentWindow && event.source !== ownerFrame.contentWindow) {
          ownerFrame.contentWindow.postMessage(
            {
              type: "maverick.app.data-changed",
              owner_app_id: payload.owner_app_id,
              resource: payload.resource || "",
              deleted_thread_id: payload.deleted_thread_id || "",
            },
            window.location.origin,
          );
        }
        return;
      }
      if (!payload.app_id) {
        return;
      }
      const senderIsMountedApp = Object.values(frameRefs.current).some((frame) => frame?.contentWindow === event.source);
      if (!senderIsMountedApp) {
        return;
      }
      if (payload.type === "maverick.app.ready") {
        const frame = frameRefs.current[payload.app_id];
        if (!frame || event.source !== frame.contentWindow) {
          return;
        }
        const latestNavigation = latestNavigationRef.current;
        if (latestNavigation.appId === payload.app_id) {
          postNavigation(frame, payload.app_id, latestNavigation.params);
        }
      }
      if (payload.type === "maverick.app.open-app") {
        onOpenApp(payload.app_id, {
          ...(payload.params || {}),
          workspace_id: payload.workspace_id || payload.params?.workspace_id || null,
        });
      }
    }

    window.addEventListener("message", handleAppMessage);
    return () => window.removeEventListener("message", handleAppMessage);
  }, [onOpenApp]);

  return (
    <section className="bs-workspace-app-panel" aria-label={`${activeApp.name} app`}>
      <div className="bs-workspace-app-surface">
        {mountedApps.map(({ app, mountKey }) => {
          const isActive = app.app_id === activeApp.app_id;
          return (
            <iframe
              aria-hidden={!isActive}
              className={`bs-workspace-app-frame ${isActive ? "is-active" : "is-hidden"}`}
              key={mountKey}
              onLoad={(event) => {
                if (app.app_id === activeApp.app_id) {
                  postNavigation(event.currentTarget, app.app_id, activeAppParams);
                }
              }}
              ref={(frame) => {
                frameRefs.current[app.app_id] = frame;
              }}
              src={app.frontend_mount}
              title={`${app.name} viewport`}
            />
          );
        })}
      </div>
    </section>
  );
}

function postNavigation(frame: HTMLIFrameElement | null | undefined, appId: string, params: AppFrameParams) {
  if (!frame?.contentWindow) {
    return;
  }
  frame.contentWindow.postMessage(
    {
      type: "maverick.app.navigate",
      app_id: appId,
      params: normalizeParams(params),
    },
    window.location.origin,
  );
}

function normalizeParams(params: AppFrameParams): Record<string, string | boolean> {
  return Object.fromEntries(
    Object.entries(params).filter(([, value]) => value !== null && value !== undefined && value !== false),
  ) as Record<string, string | boolean>;
}
