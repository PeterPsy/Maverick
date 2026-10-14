import { fireEvent, render } from "@testing-library/react";
import { afterEach, expect, it } from "vitest";
import { useShellTheme } from "./shellTheme";

function ThemeFrame() {
  useShellTheme();
  return null;
}
afterEach(() => {
  delete (window as Window & { __MAVERICK_PLATFORM_ORIGIN__?: string })
    .__MAVERICK_PLATFORM_ORIGIN__;
  delete document.documentElement.dataset.maverickTheme;
  window.history.replaceState({}, "", "/");
});

it("applies initial light theme and accepts updates only from the exact shell and supported messages", () => {
  window.history.replaceState({}, "", "/?maverick_theme=light");
  (
    window as Window & { __MAVERICK_PLATFORM_ORIGIN__?: string }
  ).__MAVERICK_PLATFORM_ORIGIN__ = "https://shell.test";
  render(<ThemeFrame />);
  expect(document.documentElement.dataset.maverickTheme).toBe("light");
  function send(
    type: string,
    origin: string,
    extra: Record<string, unknown> = {},
  ) {
    fireEvent(
      window,
      new MessageEvent("message", {
        source: window,
        origin,
        data: { type, theme: { effective: "dark" }, ...extra },
      }),
    );
  }
  send("maverick.shell.theme-changed", "https://foreign.test");
  send("maverick.app.selection-changed", "https://shell.test");
  expect(document.documentElement.dataset.maverickTheme).toBe("light");
  send("maverick.shell.theme-changed", "https://shell.test");
  expect(document.documentElement.style.colorScheme).toBe("dark");
  send("maverick.widget.context-changed", "https://shell.test", {
    context: { content: { shell_theme: { effective: "light" } } },
  });
  expect(document.documentElement.dataset.maverickTheme).toBe("light");
});
