/**
 * @vitest-environment happy-dom
 */
import { readdirSync, readFileSync, statSync } from "node:fs";
import { dirname, extname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { afterEach, describe, expect, it } from "vitest";

const currentDir = dirname(fileURLToPath(import.meta.url));
const sourceRoot = resolve(currentDir, "..");
let styleElements: HTMLStyleElement[] = [];

describe("chat light theme surfaces", () => {
  afterEach(() => {
    styleElements.forEach((styleElement) => styleElement.remove());
    styleElements = [];
    document.body.replaceChildren();
    delete document.documentElement.dataset.maverickTheme;
    delete document.documentElement.dataset.theme;
    document.documentElement.removeAttribute("style");
  });

  it("computes app popovers and rich transcript blocks from light tokens", () => {
    installStyles(resolve(currentDir, "main.css"));
    applyRootTheme("light");

    expect(computedBackgroundColor(element("div", "chatapp-agent-menu"))).toBe("rgba(255, 255, 255, 0.94)");
    expect(computedBackgroundColor(element("div", "chatapp-mention-panel"))).toBe("rgba(255, 255, 255, 0.94)");

    const markdownHost = element("div", "chatapp-agent-block__body");
    const pre = document.createElement("pre");
    markdownHost.append(pre);
    expect(computedBackgroundColor(pre)).toBe("rgba(15, 23, 42, 0.065)");
  });

  it("computes floating and sidebar widget edit surfaces from light tokens", () => {
    installStyles(resolve(currentDir, "main.css"));
    installStyles(resolve(currentDir, "../widgets/chat-floating/styles.css"));
    installStyles(resolve(currentDir, "../widgets/chat-sidebar/styles.css"));
    applyRootTheme("light");

    expect(computedBackgroundColor(element("div", "chat-floating-thread-menu__panel"))).toBe("rgba(255, 255, 255, 0.72)");
    expect(computedBackgroundColor(element("input", "chat-floating-thread-menu__rename-input"))).toBe("rgba(15, 23, 42, 0.055)");
    expect(computedBackgroundColor(element("input", "bs-chat-folder__title-input"))).toBe("rgba(15, 23, 42, 0.055)");
  });
});

describe("chat theme token governance", () => {
  it("keeps dark surface literals inside token declarations", () => {
    const offenders: string[] = [];
    for (const filePath of listCssFiles(sourceRoot)) {
      let insideTokenDeclaration = false;
      readFileSync(filePath, "utf8").split("\n").forEach((line, index) => {
        const trimmed = line.trim();
        if (trimmed.startsWith("--")) {
          insideTokenDeclaration = true;
        }
        if (containsForbiddenDarkSurfaceLiteral(line) && !insideTokenDeclaration) {
          offenders.push(`${filePath}:${index + 1}: ${trimmed}`);
        }
        if (insideTokenDeclaration && trimmed.endsWith(";")) {
          insideTokenDeclaration = false;
        }
      });
    }

    expect(offenders).toEqual([]);
  });
});

function installStyles(filePath: string): void {
  const styleElement = document.createElement("style");
  styleElement.textContent = readStyleFile(filePath);
  document.head.append(styleElement);
  styleElements.push(styleElement);
}

function readStyleFile(filePath: string, seen = new Set<string>()): string {
  if (seen.has(filePath)) {
    return "";
  }
  seen.add(filePath);
  const styles = readFileSync(filePath, "utf8");
  return styles.replace(/@import\s+"([^"]+)";/g, (_, importPath: string) => readStyleFile(resolve(dirname(filePath), importPath), seen));
}

function listCssFiles(directory: string): string[] {
  const entries = readdirSync(directory).map((entry) => join(directory, entry));
  return entries.flatMap((entry) => {
    const stats = statSync(entry);
    if (stats.isDirectory()) {
      return listCssFiles(entry);
    }
    return stats.isFile() && extname(entry) === ".css" ? [entry] : [];
  });
}

function containsForbiddenDarkSurfaceLiteral(line: string): boolean {
  return (
    line.includes("rgba(0, 0, 0") ||
    line.includes("rgba(12, 12, 14") ||
    line.includes("rgba(18, 18, 18") ||
    line.includes("#252525")
  );
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
