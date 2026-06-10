import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

const currentDir = dirname(fileURLToPath(import.meta.url));

describe("chat sidebar footer confirmation buttons", () => {
  it("uses the same glass blur treatment as the primary footer action", () => {
    const styles = readFileSync(resolve(currentDir, "styles.css"), "utf8");
    const block = styles.match(/\.bs-chat-sidebar-footer__confirm-button\s*{(?<body>[^}]*)}/)?.groups?.body ?? "";

    expect(block).toContain("-webkit-backdrop-filter: blur(18px) saturate(1.15);");
    expect(block).toContain("backdrop-filter: blur(18px) saturate(1.15);");
  });
});
