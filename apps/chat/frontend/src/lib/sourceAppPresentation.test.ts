import { describe, expect, it } from "vitest";
import {
  HISTORICAL_OPENDESIGN_THREAD_READ_ONLY,
  historicalSourceAppReadOnlyReason,
  isOpenDesignSourceApp,
  sourceAppPresentation,
} from "./sourceAppPresentation";

describe("historical OpenDesign threads", () => {
  it("recognizes Design Studio and mounted Design Studio source ids", () => {
    expect(isOpenDesignSourceApp("design-studio")).toBe(true);
    expect(isOpenDesignSourceApp("workspace-design-studio")).toBe(true);
    expect(historicalSourceAppReadOnlyReason("design-studio")).toBe(HISTORICAL_OPENDESIGN_THREAD_READ_ONLY);
  });

  it.each(["", "chat", "settings", "senses", "storage"])(
    "keeps ordinary app context %s writable",
    (sourceAppId) => {
      expect(isOpenDesignSourceApp(sourceAppId)).toBe(false);
      expect(historicalSourceAppReadOnlyReason(sourceAppId)).toBeNull();
    },
  );

  it("keeps the historical OpenDesign presentation", () => {
    expect(sourceAppPresentation("design-studio")).toEqual({
      icon: "design_services",
      kind: "opendesign",
      label: "OpenDesign",
    });
  });
});
