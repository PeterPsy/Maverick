import { describe, expect, it } from "vitest";
import type { ProviderItem } from "../api/client";
import {
  EXECUTION_FAMILY_CATALOG,
  orderedExecutionFamilies,
  safeProviderExecutionFamily,
} from "./executionFamilies";

function provider(overrides: Partial<ProviderItem>): ProviderItem {
  return {
    provider_id: "provider",
    label: "Provider",
    description: "Provider fixture",
    status: "active",
    default_model_family: null,
    ...overrides,
  };
}

describe("execution family taxonomy", () => {
  it("shows only CLI and API families that have selectable models", () => {
    expect(orderedExecutionFamilies([])).toEqual([]);
    expect(orderedExecutionFamilies([
      provider({ execution_family: "maverick_agent" }),
      provider({ provider_id: "codex", execution_family: "native_agent" }),
    ]).map((family) => family.label)).toEqual(["CLI models", "API models"]);
    expect(EXECUTION_FAMILY_CATALOG.map((family) => family.family_id)).toEqual([
      "native_agent",
      "maverick_agent",
    ]);
  });

  it("does not classify plain hosted providers as composer families", () => {
    expect(safeProviderExecutionFamily(provider({
      provider_id: "codex",
      kind: "hosted_api",
      provider_role: "model_provider",
    }))).toBeNull();
    expect(safeProviderExecutionFamily(provider({
      provider_id: "codex",
      kind: "vendor_runtime",
      provider_role: "runtime_engine",
    }))).toBeNull();
  });

  it("retains the closed legacy Codex identity", () => {
    expect(safeProviderExecutionFamily(provider({
      provider_id: "codex",
      kind: "runtime_backend",
      provider_role: "runtime_engine",
    }))).toBe("native_agent");
  });
});
