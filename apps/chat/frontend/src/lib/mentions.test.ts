import { describe, expect, it } from "vitest";
import { activeMentionAt, appReferencesFromText, applyMention, filterMentionItems, findMentionTokens, removeMentionToken } from "./mentions";
import type { MentionItem } from "./mentions";

const items: MentionItem[] = [
  { id: "test-app", label: "Test App", description: "A test application", kind: "app" },
  { id: "dynamic-views", label: "Dynamic Views", description: "Interactive views", kind: "app" },
  { id: "maverick-code-skill", label: "Maverick Code Skill", description: "Code work", kind: "skill" },
];

describe("mention autocomplete helpers", () => {
  it("detects app mentions with natural spaced names", () => {
    expect(activeMentionAt("open @Test App", "open @Test App".length)).toEqual({
      kind: "app",
      trigger: "@",
      start: 5,
      end: 14,
      query: "Test App",
    });
  });

  it("detects skill mentions from the dollar trigger", () => {
    expect(activeMentionAt("use $Maverick", "use $Maverick".length)?.kind).toBe("skill");
  });

  it("does not treat email-style symbols as mention starts", () => {
    expect(activeMentionAt("hello@test", "hello@test".length)).toBeNull();
  });

  it("filters by label, id, and description", () => {
    expect(filterMentionItems(items, "views").map((item) => item.label)).toEqual(["Dynamic Views"]);
    expect(filterMentionItems(items, "code").map((item) => item.label)).toEqual(["Maverick Code Skill"]);
  });

  it("inserts the readable name without slugifying it", () => {
    const mention = activeMentionAt("open @Tes", "open @Tes".length);
    expect(mention).not.toBeNull();
    expect(applyMention("open @Tes", mention!, items[0])).toEqual({
      value: "open @Test App ",
      cursor: "open @Test App ".length,
    });
  });

  it("finds readable mention tokens for chips", () => {
    expect(findMentionTokens("Use @Test App with $Maverick Code Skill", items).map((token) => token.text)).toEqual([
      "@Test App",
      "$Maverick Code Skill",
    ]);
  });

  it("extracts app references as app ids for runtime payloads", () => {
    expect(appReferencesFromText("Use @Test App with $Maverick Code Skill and @Test App again", items)).toEqual([
      { type: "app", app_id: "test-app", label: "Test App" },
    ]);
  });

  it("removes a chip token and its following separator space", () => {
    const token = findMentionTokens("Use @Test App now", items)[0];
    expect(removeMentionToken("Use @Test App now", token)).toEqual({
      value: "Use now",
      cursor: 4,
    });
  });
});
