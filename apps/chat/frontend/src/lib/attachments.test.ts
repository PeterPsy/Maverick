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

  it("accepts audio attachments when the hosted model declares audio input", () => {
    const file = new File(["audio"], "recording.wav", {
      type: "audio/wav",
    });

    const attachments = buildComposerAttachments([file], 0, { allowedInputModalities: ["text", "audio"] });

    expect(attachments[0].warning).toBeNull();
    expect(hasInvalidAttachments(attachments)).toBe(false);
  });

  it("blocks attachments not declared by the hosted model", () => {
    const file = new File(["image"], "frame.png", {
      type: "image/png",
    });

    const attachments = buildComposerAttachments([file], 0, { allowedInputModalities: ["text", "audio"] });

    expect(attachments[0].warning).toBe("Selected hosted model does not support this attachment type");
    expect(hasInvalidAttachments(attachments)).toBe(true);
  });
});
