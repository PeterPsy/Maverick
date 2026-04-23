import { useEffect, useRef, useState } from "react";
import { AppRegistryItem } from "../api";

type AppFrameParams = Record<string, string | boolean | null>;
const APP_EVENTS_WS_PATH = "/api/apps/events/ws";

type AppReadyMessage = {
  app_id?: string;
  deleted_thread_id?: string;
  owner_app_id?: string;
  params?: Record<string, string | boolean | null>;
  resource?: string;
  type?: string;
  workspace_id?: string;
};
type AppEventMessage = {
  owner_app_id?: string;
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
  const activeMountKey = `${activeWorkspaceId}:${activeApp.app_id}`;
  const [mountedApps, setMountedApps] = useState<Array<{ app: AppRegistryItem; mountKey: string }>>([
    { app: activeApp, mountKey: activeMountKey },
  ]);
  const [frameRevisions, setFrameRevisions] = useState<Record<string, number>>({});
  const frameRefs = useRef<Record<string, HTMLIFrameElement | null>>({});
  const latestNavigationRef = useRef<{ appId: string; params: AppFrameParams }>({
    appId: activeApp.app_id,
    params: activeAppParams,
  });
  const paramsSignature = JSON.stringify(activeAppParams);

  useEffect(() => {
    setMountedApps((current) => {
      const workspaceMountedApps = current.filter((item) => item.mountKey.startsWith(`${activeWorkspaceId}:`));
      if (workspaceMountedApps.some((item) => item.mountKey === activeMountKey)) {
        return workspaceMountedApps.map((item) =>
          item.mountKey === activeMountKey ? { app: activeApp, mountKey: activeMountKey } : item,
        );
      }
      return [...workspaceMountedApps, { app: activeApp, mountKey: activeMountKey }];
    });
  }, [activeApp, activeMountKey, activeWorkspaceId]);

  useEffect(() => {
    latestNavigationRef.current = { appId: activeApp.app_id, params: activeAppParams };
    postNavigation(frameRefs.current[activeApp.app_id], activeApp.app_id, activeAppParams);
  }, [activeApp.app_id, paramsSignature]);

  useEffect(() => {
    return connectAppEventSocket((event) => {
      if (event.type !== "maverick.app.frontend-changed" || !event.owner_app_id) {
        return;
      }
      if (event.workspace_id && event.workspace_id !== activeWorkspaceId) {
        return;
      }
      const eventMountKey = `${activeWorkspaceId}:${event.owner_app_id}`;
      setFrameRevisions((current) => ({
        ...current,
        [eventMountKey]: (current[eventMountKey] || 0) + 1,
      }));
    });
  }, [activeWorkspaceId]);

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
          const revision = frameRevisions[mountKey] || 0;
          return (
            <iframe
              aria-hidden={!isActive}
              className={`bs-workspace-app-frame ${isActive ? "is-active" : "is-hidden"}`}
              key={`${mountKey}:${revision}`}
              onLoad={(event) => {
                if (app.app_id === activeApp.app_id) {
                  postNavigation(event.currentTarget, app.app_id, activeAppParams);
                }
              }}
              ref={(frame) => {
                frameRefs.current[app.app_id] = frame;
              }}
              src={appFrameSrc(app.frontend_mount, revision)}
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

function appFrameSrc(frontendMount: string, revision: number): string {
  if (revision <= 0) {
    return frontendMount;
  }
  return mountUrlWithParam(frontendMount, "_maverick_refresh", String(revision));
}

function mountUrlWithParam(frontendMount: string, name: string, value: string): string {
  const url = new URL(frontendMount, window.location.origin);
  url.searchParams.set(name, value);
  return `${url.pathname}${url.search}${url.hash}`;
}

function connectAppEventSocket(onEvent: (event: AppEventMessage) => void): () => void {
  if (typeof WebSocket === "undefined") {
    return () => {};
  }
  let socket: WebSocket | null = null;
  let reconnectTimer: number | undefined;
  let closed = false;

  function connect() {
    socket = new WebSocket(appEventSocketUrl());
    socket.onmessage = (message) => {
      try {
        const event = JSON.parse(message.data) as AppEventMessage;
        onEvent(event);
      } catch {
        return;
      }
    };
    socket.onclose = () => {
      if (!closed) {
        reconnectTimer = window.setTimeout(connect, 1000);
      }
    };
    socket.onerror = () => {
      socket?.close();
    };
  }

  connect();
  return () => {
    closed = true;
    if (reconnectTimer !== undefined) {
      window.clearTimeout(reconnectTimer);
    }
    socket?.close();
  };
}

function appEventSocketUrl(): string {
  const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
  return `${protocol}//${window.location.host}${APP_EVENTS_WS_PATH}`;
}
