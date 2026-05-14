import { describe, expect, it } from "vitest";
import { referenceKindLabel } from "./referenceKindLabels";

describe("reference kind labels", () => {
  it("uses concrete Storage labels for files and folders", () => {
    expect(referenceKindLabel({ appId: "storage", entityType: "file", kind: "entity", summary: "markdown file, 36770 bytes" })).toBe("Markdown");
    expect(referenceKindLabel({ appId: "storage", entityType: "file", kind: "entity", summary: "image file in uploaded" })).toBe("Image");
    expect(referenceKindLabel({ appId: "storage", entityType: "file", kind: "entity" })).toBe("File");
    expect(referenceKindLabel({ appId: "storage", entityType: "folder", kind: "entity" })).toBe("Folder");
  });

  it("keeps generic record labels for non-Storage entities", () => {
    expect(referenceKindLabel({ appId: "checklist", entityType: "checklist_item", kind: "entity" })).toBe("Record");
  });
});
