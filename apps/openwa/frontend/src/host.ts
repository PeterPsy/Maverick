import { useEffect } from "react";
import {
  connectAppEventSocket,
  isExactLoopinoParentMessage,
  loopinoAppIsVisible,
} from "@loopino/pwa-cache";

type AppEvent = { type?: string; owner_app_id?: string; resource?: string };
export function useLoopinoHost(
  refresh: () => void,
  onSession: (id: string) => void,
) {
  useEffect(() => {
    const initial = new URLSearchParams(location.search).get("loopino_theme");
    if (initial === "light" || initial === "dark")
      applyTheme(initial);
    const stop = connectAppEventSocket<AppEvent>((event) => {
      if (
        event.type === "loopino.app.data-changed" &&
        event.owner_app_id === "openwa" &&
        ["connection", "sessions"].includes(event.resource || "") && loopinoAppIsVisible()
      )
        refresh();
    }, refresh);
    const listener = (event: MessageEvent) => {
      if (
        !isExactLoopinoParentMessage(event) ||
        !event.data ||
        typeof event.data !== "object"
      )
        return;
      const data = event.data;
      if (
        data.type === "loopino.app.navigate" &&
        (!data.app_id || data.app_id === "openwa") &&
        typeof data.params?.session_id === "string" &&
        data.params.session_id.length <= 128 &&
        /^[A-Za-z0-9_-]+$/.test(data.params.session_id)
      )
        onSession(data.params.session_id);
      if (
        ["loopino.shell.theme-changed", "loopino.app.navigate"].includes(data.type) &&
        ["light", "dark"].includes(data.theme?.effective)
      )
        applyTheme(data.theme.effective);
    };
    window.addEventListener("message", listener);
    document.addEventListener("keydown", preventBackspaceNavigation);
    return () => {
      stop();
      window.removeEventListener("message", listener);
      document.removeEventListener("keydown", preventBackspaceNavigation);
    };
  }, [refresh, onSession]);
}

function preventBackspaceNavigation(event: KeyboardEvent) {
  if (event.key !== "Backspace" || event.defaultPrevented || event.altKey || event.ctrlKey || event.metaKey) return;
  const target = event.composedPath()[0];
  if (target instanceof HTMLTextAreaElement && !target.disabled && !target.readOnly) return;
  if (target instanceof HTMLInputElement && !target.disabled && !target.readOnly &&
    !["button", "checkbox", "color", "file", "hidden", "image", "radio", "range", "reset", "submit"].includes(target.type)) return;
  if (target instanceof HTMLElement && target.isContentEditable) return;
  // Locked drafts and non-editable controls must not invoke browser history.
  event.preventDefault();
}

function applyTheme(theme: string) {
  document.documentElement.dataset.loopinoTheme = theme;
  document.documentElement.dataset.theme = theme;
  document.documentElement.style.colorScheme = theme;
}
