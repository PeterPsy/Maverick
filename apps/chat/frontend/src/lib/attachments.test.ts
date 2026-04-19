import { describe, expect, it } from "vitest";
import { buildComposerAttachments, formatFileSize, hasInvalidAttachments } from "./attachments";

describe("composer attachment helpers", () => {
  it("formats file sizes for composer previews", () => {
    expect(formatFileSize(512)).toBe("512 B");
    expect(formatFileSize(2048)).toBe("2.0 KB");
    expect(formatFileSize(2 * 1024 * 1024)).toBe("2.0 MB");
  });

  it("marks files over the local v3 UI validation limit", () => {
    const file = new File([new Uint8Array(26 * 1024 * 1024)], "large.bin", {
      type: "application/octet-stream",
    });
    const attachments = buildComposerAttachments([file]);
    expect(attachments).toHaveLength(1);
    expect(hasInvalidAttachments(attachments)).toBe(true);
  });

  it("marks unsupported file types before submit", () => {
    const file = new File(["binary"], "script.sh", {
      type: "application/x-sh",
    });
    const attachments = buildComposerAttachments([file]);
    expect(attachments[0].warning).toBe("Tipo file non supportato");
  });
});
