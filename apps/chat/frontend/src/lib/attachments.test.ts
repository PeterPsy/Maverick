import { describe, expect, it } from "vitest";
import { buildComposerAttachments, formatFileSize, hasInvalidAttachments, refreshComposerAttachmentWarnings } from "./attachments";

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

  it.each([
    "archive.zip", "ARCHIVE.ZIP", "archive.zipx", "archive.rar", "archive.7z",
    "archive.tar", "archive.tar.gz", "archive.tgz", "archive.tar.bz2", "archive.tbz2",
    "archive.tar.xz", "archive.txz", "archive.tar.lz", "archive.tar.lzma", "archive.tlz",
    "archive.lzo", "archive.lz4", "archive.Z", "archive.tar.zst", "archive.tzst", "archive.br",
    "archive.cab", "archive.arj", "archive.ace", "archive.arc", "archive.lzh", "archive.lha",
    "archive.sit", "archive.sitx", "archive.cpio", "archive.xar", "archive.zpaq", "archive.paq",
    "archive.pea", "archive.alz",
  ])("accepts %s even when the browser has no specific MIME type", (name) => {
    for (const type of ["", "application/octet-stream"]) {
      const [attachment] = buildComposerAttachments([new File(["archive"], name, { type })]);

      expect(attachment.warning).toBeNull();
      expect(attachment.isImage).toBe(false);
      expect(attachment.isAudio).toBe(false);
      expect(attachment.objectUrl).toBeNull();
    }
  });

  it.each([
    "application/zip", "application/x-zip-compressed", "application/vnd.rar",
    "application/x-rar-compressed", "application/x-7z-compressed", "application/x-tar",
    "application/gzip", "application/x-gzip", "application/x-bzip2", "application/x-xz",
    "application/zstd", "application/vnd.ms-cab-compressed",
  ])("accepts an archive identified by %s without an extension", (type) => {
    const attachments = buildComposerAttachments([new File(["archive"], "download", { type })]);

    expect(hasInvalidAttachments(attachments)).toBe(false);
  });

  it("does not accept an executable with an archive extension inside its name", () => {
    const [attachment] = buildComposerAttachments([
      new File(["binary"], "archive.zip.exe", { type: "application/octet-stream" }),
    ]);

    expect(attachment.warning).toBe("Unsupported file type");
  });

  it("keeps the size and count limits for archive attachments", () => {
    const largeArchive = new File([new Uint8Array(26 * 1024 * 1024)], "large.zip");
    expect(buildComposerAttachments([largeArchive])[0].warning).toBe("File exceeds the 25.0 MB limit");

    const archives = Array.from({ length: 9 }, (_, index) => new File(["archive"], `${index}.zip`));
    expect(buildComposerAttachments(archives)).toHaveLength(8);
    expect(buildComposerAttachments(archives, 7)).toHaveLength(1);
  });

  it("requires file input support for archives and refreshes the warning when the model changes", () => {
    const archives = buildComposerAttachments([new File(["archive"], "archive.zip")]);
    const restricted = refreshComposerAttachmentWarnings(archives, { allowedInputModalities: ["text", "image", "document"] });
    expect(restricted[0].warning).toBe("Selected hosted model does not support this attachment type");

    const allowed = refreshComposerAttachmentWarnings(restricted, { allowedInputModalities: ["text", "file"] });
    expect(allowed[0].warning).toBeNull();
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
