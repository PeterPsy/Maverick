import { describe, expect, it } from "vitest";
import { buildComposerAttachments, formatFileSize, hasInvalidAttachments } from "./attachments";

describe("composer attachment helpers", () => {
  it("formats file sizes for composer previews", () => {
    expect(formatFileSize(512)).toBe("512 B");
    expect(formatFileSize(2048)).toBe("2.0 KB");
    expect(formatFileSize(2 * 1024 * 1024)).toBe("2.0 MB");
  });

  it("marks files over the local UI validation limit", () => {
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
    expect(attachments[0].warning).toBe("Unsupported file type");
  });

  it("accepts m4a audio attachments when the browser omits the MIME type", () => {
    const file = new File(["audio"], "AUDIO-2026-06-25-22-00.m4a", {
      type: "",
    });

    const attachments = buildComposerAttachments([file]);

    expect(attachments[0].warning).toBeNull();
    expect(attachments[0].type).toBe("audio/mp4");
    expect(attachments[0].isAudio).toBe(true);
    expect(hasInvalidAttachments(attachments)).toBe(false);
  });

  it("blocks non-image attachments for hosted chat image input", () => {
    const file = new File(["notes"], "notes.txt", {
      type: "text/plain",
    });

    const attachments = buildComposerAttachments([file], 0, { inputMode: "image" });

    expect(attachments[0].warning).toBe("Hosted chat supports image attachments only");
    expect(hasInvalidAttachments(attachments)).toBe(true);
  });

  it("blocks all attachments for hosted chat models without attachment input", () => {
    const file = new File(["image"], "frame.png", {
      type: "image/png",
    });

    const attachments = buildComposerAttachments([file], 0, { inputMode: "none" });

    expect(attachments[0].warning).toBe("Selected hosted model does not support attachments");
    expect(hasInvalidAttachments(attachments)).toBe(true);
  });
});
