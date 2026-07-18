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

    expect(computedBackgroundColor(element("div", "chatapp-agent-menu"))).toBe("rgba(255, 255, 255, 0.96)");
    expect(computedBackgroundColor(element("div", "chatapp-provider-menu"))).toBe("rgba(255, 255, 255, 0.96)");
    expect(computedBackgroundColor(element("div", "chatapp-mention-panel"))).toBe("rgba(255, 255, 255, 0.94)");

    const markdownHost = element("div", "chatapp-agent-block__body");
    const pre = document.createElement("pre");
    markdownHost.append(pre);
    expect(computedBackgroundColor(pre)).toBe("rgba(15, 23, 42, 0.065)");
  });

  it("removes light transcript shadows and the top dark fade", () => {
    installStyles(resolve(currentDir, "main.css"));
    applyRootTheme("light");

    expect(rootToken("--chatapp-chat-top-fade")).toBe("none");
    expect(computedBoxShadow(element("div", "chatapp-human-message"))).toBe("none");
    expect(computedBoxShadow(element("section", "chatapp-agent-block"))).toBe("none");
    expect(computedBoxShadow(element("div", "chatapp-structured-card"))).toBe("none");
    expect(computedBoxShadow(element("div", "chatapp-tool-inline"))).toBe("none");
    expect(computedBoxShadow(element("section", "chatapp-tool-call-panel"))).toBe("none");
    expect(computedBoxShadow(element("div", "chatapp-diff-card"))).toBe("none");
  });

  it("uses readable light colors for human message metadata and full-access badges", () => {
    installStyles(resolve(currentDir, "main.css"));
    applyRootTheme("light");

    const humanMessage = element("div", "chatapp-human-message");
    const referenceChip = document.createElement("span");
    referenceChip.className = "chatapp-message-reference-chip is-app";
    const referenceKind = document.createElement("span");
    referenceKind.className = "chatapp-message-reference-chip__kind";
    referenceChip.append(referenceKind);
    humanMessage.append(referenceChip);

    const copyButton = document.createElement("button");
    copyButton.className = "chatapp-message-action chatapp-message-action--copy";
    humanMessage.append(copyButton);

    const footer = document.createElement("div");
    footer.className = "chatapp-message-mobile-footer";
    const timestamp = document.createElement("time");
    timestamp.className = "chatapp-bubble__time";
    footer.append(timestamp);
    humanMessage.append(footer);

    expect(computedBackgroundColor(referenceChip)).toBe("rgba(255, 255, 255, 0.1)");
    expect(computedBorderColor(referenceChip)).toBe("rgba(255, 255, 255, 0.16)");
    expect(computedColor(referenceChip)).toBe("rgba(255, 255, 255, 0.88)");
    expect(computedColor(referenceKind)).toBe("rgba(255, 255, 255, 0.56)");
    expect(computedColor(copyButton)).toBe("rgba(255, 255, 255, 0.58)");
    expect(computedColor(timestamp)).toBe("rgba(255, 255, 255, 0.58)");

    const fullAccessChip = element("span", "chatapp-execution-chip is-full-access");
    expect(computedColor(fullAccessChip)).toBe("#9a3412");
    expect(computedBorderColor(fullAccessChip)).toBe("rgba(234, 88, 12, 0.34)");
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

describe("chat multi-agent board control", () => {
  it("masks the live animation so it remains a border glow", () => {
    const styles = readStyleFile(resolve(currentDir, "chat/transcript/loading.css"));

    expect(styles).toMatch(
      /\.chatapp-live-border-glow::after\s*{[\s\S]*inset:\s*1px;[\s\S]*background:\s*var\(--chatapp-live-border-fill,\s*var\(--chatapp-solid-surface\)\);/,
    );
    expect(styles).toMatch(/\.chatapp-inter-agent-board-button\.is-live\s*{[\s\S]*background:\s*transparent;/);
    expect(styles).toMatch(/\.chatapp-live-border-glow__layer--bright\s*{[\s\S]*border-radius:\s*inherit;/);
    expect(styles).toMatch(/\.chatapp-live-border-glow__layer--rim\s*{[\s\S]*border-radius:\s*inherit;/);
  });

  it("keeps the participant input header large and bounds only long summaries", () => {
    const styles = readStyleFile(resolve(currentDir, "chat/transcript/inter-agent.css"));

    expect(styles).toMatch(
      /\.chatapp-inter-agent-graph__transcript-title summary\s*{[\s\S]*min-height:\s*4\.25rem;/,
    );
    expect(styles).toMatch(
      /\.chatapp-inter-agent-graph__input-summary p\s*{[\s\S]*max-height:\s*min\(14rem, 35vh\);[\s\S]*overflow:\s*auto;/,
    );
  });

  it("uses the chat background behind dots and keeps node activity as a bounded preview", () => {
    const styles = readStyleFile(resolve(currentDir, "chat/transcript/inter-agent.css"));

    expect(styles).toMatch(
      /\.chatapp-inter-agent-graph\.chatapp-agent-nodes-view \.chatapp-inter-agent-graph__canvas\s*{[\s\S]*background:\s*var\(--maverick-bg\);/,
    );
    expect(styles).toMatch(
      /\.chatapp-inter-agent-graph\.chatapp-agent-nodes-view \.chatapp-inter-agent-graph__board\s*{[\s\S]*background:\s*var\(--maverick-bg\);/,
    );
    expect(styles).not.toMatch(/\.chatapp-inter-agent-graph\.chatapp-agent-nodes-view \.chatapp-inter-agent-graph__board::after/);
    expect(styles).toMatch(
      /\.chatapp-inter-agent-graph__node-activity p\s*{[\s\S]*max-height:\s*2\.1rem;[\s\S]*-webkit-line-clamp:\s*2;/,
    );
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

function computedBoxShadow(node: Element): string {
  return getComputedStyle(node).boxShadow;
}

function computedColor(node: Element): string {
  return getComputedStyle(node).color;
}

function computedBorderColor(node: Element): string {
  return getComputedStyle(node).borderColor;
}

function rootToken(name: string): string {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
}
