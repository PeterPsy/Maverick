import { useCallback, useEffect, useMemo } from "react";
import {
  mountedAppIdFromPath,
  openApp,
  postToShell,
  isMaverickParentMessage,
  viewFromAppPage,
} from "../../lib/shellNavigation";
import { useShellTheme } from "../../lib/shellTheme";
import { createAction } from "../../navigation";
import { useSidebarContext } from "../useSidebarContext";

const WIDGET_ID = "marta-ops-sidebar-footer";

export function MartaOpsSidebarFooter() {
  useShellTheme();
  const appId = useMemo(() => mountedAppIdFromPath(), []);
  const { params, loading, error, retry } = useSidebarContext(appId, WIDGET_ID);
  const action = createAction(viewFromAppPage(params.app_page) || "today");
  const available = !loading && !error;
  const openCreate = useCallback(() => {
    openApp(appId, {
      app_page: action.view,
      [action.param]: true,
      [`${action.param}_request_id`]: crypto.randomUUID(),
    });
  }, [appId, action.view, action.param]);

  useEffect(() => {
    function postActionState() {
      postToShell({
        type: "maverick.widget.primary-action.state",
        owner_app_id: appId,
        widget_id: WIDGET_ID,
        available,
        label: action.label,
      });
    }
    function handleShellMessage(event: MessageEvent) {
      if (!isMaverickParentMessage(event)) return;
      const message = event.data;
      if (message.owner_app_id !== appId || message.widget_id !== WIDGET_ID)
        return;
      if (message.type === "maverick.widget.primary-action.query")
        postActionState();
      if (
        message.type === "maverick.widget.primary-action.invoke" &&
        available
      ) {
        openCreate();
      }
    }
    postActionState();
    window.addEventListener("message", handleShellMessage);
    return () => window.removeEventListener("message", handleShellMessage);
  }, [appId, action.label, available, openCreate]);

  return (
    <main className="marta-sidebar-footer-widget">
      <button
        className="marta-sidebar-footer-button"
        disabled={loading}
        onClick={() => (error ? retry() : openCreate())}
        type="button"
      >
        <span aria-hidden="true" className="marta-sidebar-footer-plus" />
        <span>{error ? "Riprova" : action.label}</span>
      </button>
    </main>
  );
}
