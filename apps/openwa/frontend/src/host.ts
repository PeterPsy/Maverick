import { useEffect } from "react";
import {
  connectAppEventSocket,
  isExactMaverickParentMessage,
  maverickAppIsVisible,
} from "@maverick/pwa-cache";

type AppEvent = { type?: string; owner_app_id?: string; resource?: string };
export function useMaverickHost(
  refresh: () => void,
  onSession: (id: string) => void,
) {
  useEffect(() => {
    const initial = new URLSearchParams(location.search).get("maverick_theme");
    if (initial === "light" || initial === "dark")
      applyTheme(initial);
    const stop = connectAppEventSocket<AppEvent>((event) => {
      if (
        event.type === "maverick.app.data-changed" &&
        event.owner_app_id === "openwa" &&
        ["connection", "sessions"].includes(event.resource || "") && maverickAppIsVisible()
      )
        refresh();
    }, refresh);
    const listener = (event: MessageEvent) => {
      if (
        !isExactMaverickParentMessage(event) ||
        !event.data ||
        typeof event.data !== "object"
      )
        return;
      const data = event.data;
      if (
        data.type === "maverick.app.navigate" &&
        (!data.app_id || data.app_id === "openwa") &&
        typeof data.params?.session_id === "string" &&
        data.params.session_id.length <= 128 &&
        /^[A-Za-z0-9_-]+$/.test(data.params.session_id)
      )
        onSession(data.params.session_id);
      if (
        ["maverick.shell.theme-changed", "maverick.app.navigate"].includes(data.type) &&
        ["light", "dark"].includes(data.theme?.effective)
      )
        applyTheme(data.theme.effective);
    };
    window.addEventListener("message", listener);
    return () => {
      stop();
      window.removeEventListener("message", listener);
    };
  }, [refresh, onSession]);
}

function applyTheme(theme: string) {
  document.documentElement.dataset.maverickTheme = theme;
  document.documentElement.dataset.theme = theme;
  document.documentElement.style.colorScheme = theme;
}
