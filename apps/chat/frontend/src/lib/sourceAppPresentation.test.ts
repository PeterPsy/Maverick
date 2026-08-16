import { describe, expect, it } from "vitest";
import { delegatedChatSourceAppId } from "./sourceAppPresentation";

describe("delegatedChatSourceAppId", () => {
  it("keeps Design Studio and mounted Design Studio source ids", () => {
    expect(delegatedChatSourceAppId("design-studio")).toBe("design-studio");
    expect(delegatedChatSourceAppId("workspace-design-studio")).toBe("workspace-design-studio");
  });

  it.each(["", "chat", "settings", "senses", "storage"])(
    "does not delegate ordinary app context %s",
    (sourceAppId) => {
      expect(delegatedChatSourceAppId(sourceAppId)).toBe("");
    },
  );
});
