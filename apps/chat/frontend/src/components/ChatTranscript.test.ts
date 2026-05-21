import { describe, expect, it } from "vitest";
import { fallbackMatchesForAppReference } from "../lib/messageReferenceMatches";
import type { AppReference } from "../api/client";

describe("chat transcript reference fallback matches", () => {
  it("matches entity references by stable ref marker when the label changed", () => {
    const reference: AppReference = {
      type: "entity",
      app_id: "checklist",
      entity_type: "checklist",
      entity_id: "check_123",
      label: "Renamed launch",
      summary: "server summary",
      deep_link: "/app/checklist/checklists/check_123",
    };

    expect(fallbackMatchesForAppReference("Review @Old launch [ref:checklist/checklist/check_123]", reference)).toEqual([
      {
        kind: "entity",
        id: "entity:checklist:checklist:check_123",
        appId: "checklist",
        entityType: "checklist",
        label: "Renamed launch",
        start: 7,
        end: 54,
        deepLink: "/app/checklist/checklists/check_123",
        summary: "server summary",
      },
    ]);
  });

  it("marks deleted entity references found by stable ref marker", () => {
    const reference: AppReference = {
      type: "entity",
      app_id: "checklist",
      entity_type: "checklist",
      entity_id: "missing",
      label: "missing",
      summary: "",
      exists: false,
    };

    expect(fallbackMatchesForAppReference("Review @Old launch [ref:checklist/checklist/missing]", reference)[0]).toMatchObject({
      kind: "entity",
      id: "entity:checklist:checklist:missing",
      label: "missing",
      exists: false,
    });
  });

  it("falls back to the marker range when the marker has no direct mention prefix", () => {
    const reference: AppReference = {
      type: "entity",
      app_id: "checklist",
      entity_type: "checklist",
      entity_id: "check_123",
      label: "Renamed launch",
    };

    expect(fallbackMatchesForAppReference("Compare @Chat\nthen [ref:checklist/checklist/check_123]", reference)).toEqual([
      {
        kind: "entity",
        id: "entity:checklist:checklist:check_123",
        appId: "checklist",
        entityType: "checklist",
        label: "Renamed launch",
        start: 19,
        end: 54,
      },
    ]);
  });

  it("does not consume plain app_id text before a marker", () => {
    const reference: AppReference = {
      type: "entity",
      app_id: "checklist",
      entity_type: "checklist",
      entity_id: "check_123",
      label: "Renamed launch",
    };

    expect(fallbackMatchesForAppReference("Compare app_id:chat then [ref:checklist/checklist/check_123]", reference)).toEqual([
      {
        kind: "entity",
        id: "entity:checklist:checklist:check_123",
        appId: "checklist",
        entityType: "checklist",
        label: "Renamed launch",
        start: 25,
        end: 60,
      },
    ]);
  });
});
