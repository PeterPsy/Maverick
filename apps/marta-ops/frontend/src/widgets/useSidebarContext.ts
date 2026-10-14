import { useCallback, useEffect, useRef, useState } from "react";
import { isLoopinoParentMessage, postToShell } from "../lib/shellNavigation";

type Params = Record<string, unknown>;
type WidgetContext = {
  owner_app_id?: string;
  widget_id?: string;
  content?: {
    payload?: { active_app_params?: Params; is_mobile_layout?: boolean };
  };
};

export function useSidebarContext(appId: string, widgetId: string) {
  const [params, setParams] = useState<Params>({});
  const [isMobile, setIsMobile] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [attempt, setAttempt] = useState(0);
  const hostParams = useRef("");
  const retry = useCallback(() => setAttempt((value) => value + 1), []);

  useEffect(() => {
    const controller = new AbortController();
    let receivedLiveContext = false;
    setLoading(true);
    setError("");

    function matchesContext(context: WidgetContext) {
      return (
        (!context.owner_app_id || context.owner_app_id === appId) &&
        (!context.widget_id || context.widget_id === widgetId)
      );
    }

    function applyContext(context: WidgetContext) {
      if (
        (context.owner_app_id && context.owner_app_id !== appId) ||
        (context.widget_id && context.widget_id !== widgetId)
      )
        return;
      const payload = context.content?.payload;
      const key = JSON.stringify(payload?.active_app_params || {});
      if (key !== hostParams.current) {
        hostParams.current = key;
        setParams(payload?.active_app_params || {});
      }
      setIsMobile(payload?.is_mobile_layout === true);
      setLoading(false);
      setError("");
    }

    function handleMessage(event: MessageEvent) {
      if (!isLoopinoParentMessage(event)) return;
      const message = event.data;
      if (
        message.type === "loopino.widget.context-changed" &&
        message.context &&
        matchesContext(message.context)
      ) {
        receivedLiveContext = true;
        applyContext(message.context);
      }
      if (
        message.type === "loopino.app.selection-changed" &&
        message.owner_app_id === appId &&
        message.selection &&
        typeof message.selection === "object"
      ) {
        setParams(message.selection);
      }
    }

    async function load() {
      const token =
        new URLSearchParams(window.location.hash.slice(1)).get("context") ||
        new URLSearchParams(window.location.search).get("context");
      if (!token) {
        if (!receivedLiveContext) setLoading(false);
        return;
      }
      try {
        const response = await fetch(
          `/api/apps/widgets/context/${encodeURIComponent(token)}`,
          {
            credentials: "same-origin",
            headers: { Accept: "application/json" },
            signal: controller.signal,
          },
        );
        if (!response.ok) throw new Error("Contesto sidebar non disponibile.");
        const payload = await response.json();
        if (!payload.context || typeof payload.context !== "object")
          throw new Error("Contesto sidebar non valido.");
        if (!matchesContext(payload.context))
          throw new Error("Contesto sidebar non valido.");
        if (!controller.signal.aborted && !receivedLiveContext)
          applyContext(payload.context);
      } catch (error) {
        if (!controller.signal.aborted && !receivedLiveContext) {
          setError(
            error instanceof Error
              ? error.message
              : "Contesto sidebar non disponibile.",
          );
          setLoading(false);
        }
      }
    }

    window.addEventListener("message", handleMessage);
    void load();
    postToShell({
      type: "loopino.widget.ready",
      owner_app_id: appId,
      widget_id: widgetId,
    });
    return () => {
      controller.abort();
      window.removeEventListener("message", handleMessage);
    };
  }, [appId, widgetId, attempt]);

  return { params, isMobile, loading, error, retry };
}
