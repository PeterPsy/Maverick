import { useEffect, useRef, useState } from "react";
import { AppRegistryItem } from "../api";

type AppFrameParams = Record<string, string | boolean | null>;

export function AppFrameHost({
  activeApp,
  activeAppParams,
}: {
  activeApp: AppRegistryItem;
  activeAppParams: AppFrameParams;
}) {
  const [mountedApps, setMountedApps] = useState<AppRegistryItem[]>([activeApp]);
  const frameRefs = useRef<Record<string, HTMLIFrameElement | null>>({});
  const paramsSignature = JSON.stringify(activeAppParams);

  useEffect(() => {
    setMountedApps((current) => {
      if (current.some((app) => app.app_id === activeApp.app_id)) {
        return current;
      }
      return [...current, activeApp];
    });
  }, [activeApp]);

  useEffect(() => {
    postNavigation(frameRefs.current[activeApp.app_id], activeApp.app_id, activeAppParams);
  }, [activeApp.app_id, paramsSignature]);

  return (
    <section className="bs-workspace-app-panel" aria-label={`${activeApp.name} app`}>
      <div className="bs-workspace-app-surface">
        {mountedApps.map((app) => {
          const isActive = app.app_id === activeApp.app_id;
          return (
            <iframe
              aria-hidden={!isActive}
              className={`bs-workspace-app-frame ${isActive ? "is-active" : "is-hidden"}`}
              key={app.app_id}
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
