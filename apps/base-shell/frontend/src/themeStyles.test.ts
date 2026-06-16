/**
 * @vitest-environment happy-dom
 */
import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { afterEach, describe, expect, it } from "vitest";

const currentDir = dirname(fileURLToPath(import.meta.url));
let styleElement: HTMLStyleElement | null = null;

describe("base shell light theme surfaces", () => {
  afterEach(() => {
    styleElement?.remove();
    styleElement = null;
    document.body.replaceChildren();
    delete document.documentElement.dataset.maverickTheme;
    delete document.documentElement.dataset.theme;
    document.documentElement.removeAttribute("style");
  });

  it("computes key shell surfaces from light semantic tokens", () => {
    installShellStyles();
    applyRootTheme("light");

    expect(computedBackgroundColor(element("div", "bs-ui-dialog__backdrop"))).toBe("rgba(15, 23, 42, 0.22)");
    expect(computedBackgroundColor(element("div", "bs-ui-dialog__panel"))).toBe("rgba(255, 255, 255, 0.96)");
    expect(computedBackgroundColor(element("div", "bs-capture-overlay"))).toBe("rgba(15, 23, 42, 0.1)");
    expect(computedBackgroundColor(element("div", "bs-capture-overlay__hint"))).toBe("rgba(255, 255, 255, 0.92)");

    const appGridPanel = element("section", "bs-app-grid-panel");
    expect(getComputedStyle(appGridPanel).backgroundImage).toContain("rgba(255, 255, 255, 0.88)");
  });

  it("routes shell fade and overlay selectors through semantic tokens", () => {
    const styles = readStyleFile(resolve(currentDir, "styles/main.css"));

    expect(cssBlock(styles, ".bs-sidebar__details::before")).toContain("background: var(--maverick-scroll-fade-top);");
    expect(cssBlock(styles, ".bs-sidebar__details::after")).toContain("background: var(--maverick-scroll-fade-bottom);");
    expect(cssBlock(styles, ".bs-shell.is-mobile-layout::before")).toContain("background: var(--maverick-mobile-safe-area-fade);");
    expect(cssBlock(styles, ".bs-app-grid-panel,\n.bs-empty-panel")).toContain("background: var(--maverick-panel-gradient);");
  });
});

function installShellStyles(): void {
  styleElement = document.createElement("style");
  styleElement.textContent = readStyleFile(resolve(currentDir, "styles/main.css"));
  document.head.append(styleElement);
}

function readStyleFile(filePath: string, seen = new Set<string>()): string {
  if (seen.has(filePath)) {
    return "";
  }
  seen.add(filePath);
  const styles = readFileSync(filePath, "utf8");
  return styles.replace(/@import\s+"([^"]+)";/g, (_, importPath: string) => readStyleFile(resolve(dirname(filePath), importPath), seen));
}

function cssBlock(styles: string, selector: string): string {
  const escapedSelector = selector.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  const matches = [...styles.matchAll(new RegExp(`${escapedSelector}\\s*{([\\s\\S]*?)}`, "g"))];
  return matches.at(-1)?.[1] || "";
}

function applyRootTheme(theme: "dark" | "light"): void {
  document.documentElement.dataset.maverickTheme = theme;
  document.documentElement.dataset.theme = theme;
  document.documentElement.style.colorScheme = theme;
}

function element(tagName: string, className: string): HTMLElement {
  const node = document.createElement(tagName);
  node.className = className;
  document.body.append(node);
  return node;
}

function computedBackgroundColor(node: Element): string {
  return getComputedStyle(node).backgroundColor;
}
