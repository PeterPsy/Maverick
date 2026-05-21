import { describe, expect, it } from "vitest";
import { activeMentionAt, appReferencesFromText, applyMention, filterMentionItems, findMentionTokens, removeMentionToken } from "./mentions";
import type { MentionItem } from "./mentions";

const items: MentionItem[] = [
  { id: "test-app", label: "Test App", description: "A test application", kind: "app" },
  { id: "dynamic-views", label: "Dynamic Views", description: "Interactive views", kind: "app" },
  {
    id: "entity:checklist:checklist:check_123",
    label: "Agency launch",
    description: "Checklist",
    kind: "entity",
    reference: {
      type: "entity",
      app_id: "checklist",
      entity_type: "checklist",
      entity_id: "check_123",
      label: "Agency launch",
      summary: "1/3 checked",
      deep_link: "/app/checklist/checklists/check_123",
    },
  },
  {
    id: "entity:storage:folder:generated:Client%20Docs/",
    label: "Client Docs",
    description: "storage · folder · Storage folder",
    kind: "entity",
    reference: {
      type: "entity",
      app_id: "storage",
      entity_type: "folder",
      entity_id: "generated:Client%20Docs/",
      label: "Client Docs",
      summary: "Storage folder in generated",
      deep_link: "/app/storage/folders/generated/Client%20Docs",
    },
  },
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

  it("filters entity references by reference identity, plural forms, and query tokens", () => {
    expect(filterMentionItems(items, "checklists").map((item) => item.label)).toEqual(["Agency launch"]);
    expect(filterMentionItems(items, "agency check_123").map((item) => item.label)).toEqual(["Agency launch"]);
  });

  it("inserts the readable name without slugifying it", () => {
    const mention = activeMentionAt("open @Tes", "open @Tes".length);
    expect(mention).not.toBeNull();
    expect(applyMention("open @Tes", mention!, items[0])).toEqual({
      value: "open @Test App ",
      cursor: "open @Test App ".length,
    });
  });

  it("inserts selected entity references as stable runtime tokens", () => {
    const mention = activeMentionAt("review @Agency", "review @Agency".length);
    expect(mention).not.toBeNull();

    const applied = applyMention("review @Agency", mention!, items[2]);

    expect(applied).toEqual({
      value: "review @Agency launch [ref:checklist/checklist/check_123] ",
      cursor: "review @Agency launch [ref:checklist/checklist/check_123] ".length,
    });
    expect(appReferencesFromText(applied.value, items)).toEqual([
      {
        type: "entity",
        app_id: "checklist",
        entity_type: "checklist",
        entity_id: "check_123",
        label: "Agency launch",
        summary: "1/3 checked",
        deep_link: "/app/checklist/checklists/check_123",
      },
    ]);
  });

  it("finds readable mention tokens for chips", () => {
    expect(findMentionTokens("Use @Test App with $Maverick Code Skill", items).map((token) => token.text)).toEqual([
      "@Test App",
      "$Maverick Code Skill",
    ]);
  });

  it("extracts app and entity references for runtime payloads", () => {
    expect(
      appReferencesFromText(
        "Use @Test App with $Maverick Code Skill and @Agency launch [ref:checklist/checklist/check_123]",
        items,
      ),
    ).toEqual([
      { type: "app", app_id: "test-app", label: "Test App" },
      {
        type: "entity",
        app_id: "checklist",
        entity_type: "checklist",
        entity_id: "check_123",
        label: "Agency launch",
        summary: "1/3 checked",
        deep_link: "/app/checklist/checklists/check_123",
      },
    ]);
  });

  it("extracts pasted entity reference markers without a picker item", () => {
    expect(appReferencesFromText("Review @Old launch [ref:checklist/checklist/check_123]", [])).toEqual([
      {
        type: "entity",
        app_id: "checklist",
        entity_type: "checklist",
        entity_id: "check_123",
        label: "Old launch",
      },
    ]);
  });

  it("keeps encoded storage folder ids intact in reference markers", () => {
    const applied = applyMention("Open @Client", activeMentionAt("Open @Client", "Open @Client".length)!, items[3]);

    expect(applied.value).toBe("Open @Client Docs [ref:storage/folder/generated:Client%20Docs/] ");
    expect(appReferencesFromText(applied.value, items)).toEqual([
      {
        type: "entity",
        app_id: "storage",
        entity_type: "folder",
        entity_id: "generated:Client%20Docs/",
        label: "Client Docs",
        summary: "Storage folder in generated",
        deep_link: "/app/storage/folders/generated/Client%20Docs",
      },
    ]);
  });

  it("does not let pasted markers overwrite picker-provided entity metadata", () => {
    expect(appReferencesFromText("@Agency launch [ref:checklist/checklist/check_123]", items)).toEqual([
      {
        type: "entity",
        app_id: "checklist",
        entity_type: "checklist",
        entity_id: "check_123",
        label: "Agency launch",
        summary: "1/3 checked",
        deep_link: "/app/checklist/checklists/check_123",
      },
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
