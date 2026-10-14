import { useEffect } from "react";
import { isLoopinoParentMessage } from "./shellNavigation";

export function applyShellTheme(value: unknown) {
  if (!value || typeof value !== "object") return;
  const theme = value as { effective?: unknown; color_scheme?: unknown };
  const effective = theme.effective ?? theme.color_scheme;
  if (effective !== "dark" && effective !== "light") return;
  const root = document.documentElement;
  root.dataset.loopinoTheme = effective;
  root.dataset.theme = effective;
  root.style.colorScheme = effective;
}

export function useShellTheme() {
  useEffect(() => {
    const search = new URLSearchParams(window.location.search);
    const hash = new URLSearchParams(window.location.hash.slice(1));
    applyShellTheme({
      effective:
        search.get("loopino_theme") ||
        hash.get("loopino_theme") ||
        search.get("loopino_color_scheme") ||
        hash.get("loopino_color_scheme") ||
        "dark",
    });
    function handleMessage(event: MessageEvent) {
      if (!isLoopinoParentMessage(event)) return;
      const message = event.data;
      if (
        message.type === "loopino.shell.theme-changed" ||
        message.type === "loopino.app.navigate"
      )
        applyShellTheme(message.theme);
      if (message.type === "loopino.widget.context-changed")
        applyShellTheme(
          message.context?.content?.shell_theme || message.context?.shell_theme,
        );
    }
    window.addEventListener("message", handleMessage);
    return () => window.removeEventListener("message", handleMessage);
  }, []);
}
