import { useEffect } from "react";
import { isMaverickParentMessage } from "./shellNavigation";

export function applyShellTheme(value: unknown) {
  if (!value || typeof value !== "object") return;
  const theme = value as { effective?: unknown; color_scheme?: unknown };
  const effective = theme.effective ?? theme.color_scheme;
  if (effective !== "dark" && effective !== "light") return;
  const root = document.documentElement;
  root.dataset.maverickTheme = effective;
  root.dataset.theme = effective;
  root.style.colorScheme = effective;
}

export function useShellTheme() {
  useEffect(() => {
    const search = new URLSearchParams(window.location.search);
    const hash = new URLSearchParams(window.location.hash.slice(1));
    applyShellTheme({
      effective:
        search.get("maverick_theme") ||
        hash.get("maverick_theme") ||
        search.get("maverick_color_scheme") ||
        hash.get("maverick_color_scheme") ||
        "dark",
    });
    function handleMessage(event: MessageEvent) {
      if (!isMaverickParentMessage(event)) return;
      const message = event.data;
      if (
        message.type === "maverick.shell.theme-changed" ||
        message.type === "maverick.app.navigate"
      )
        applyShellTheme(message.theme);
      if (message.type === "maverick.widget.context-changed")
        applyShellTheme(
          message.context?.content?.shell_theme || message.context?.shell_theme,
        );
    }
    window.addEventListener("message", handleMessage);
    return () => window.removeEventListener("message", handleMessage);
  }, []);
}
