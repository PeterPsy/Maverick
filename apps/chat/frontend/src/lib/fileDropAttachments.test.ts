import { describe, expect, it } from "vitest";
import { filesFromDataTransfer, hasFileDropData } from "./fileDropAttachments";

describe("file drop attachments", () => {
  it("detects browser file drags from data transfer types", () => {
    expect(hasFileDropData({ types: ["text/plain", "Files"] })).toBe(true);
    expect(hasFileDropData({ types: ["text/plain"] })).toBe(false);
  });

  it("returns only File objects from a drop payload", () => {
    const file = new File(["notes"], "notes.txt", { type: "text/plain" });

    expect(filesFromDataTransfer({ files: [file, "not-a-file"] as unknown as ArrayLike<File> })).toEqual([file]);
  });
});
