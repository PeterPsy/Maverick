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
  it("keeps the normative order and exact product copy", () => {
    expect(orderedExecutionFamilies([])).toEqual(EXECUTION_FAMILY_CATALOG.map(
      (family) => ({ ...family, order: EXECUTION_FAMILY_CATALOG.indexOf(family) }),
    ));
  });

  it("does not classify a hosted provider as native from a vendor label or id", () => {
    expect(safeProviderExecutionFamily(provider({
      provider_id: "codex",
      kind: "hosted_api",
      provider_role: "model_provider",
    }))).toBe("hosted_text");
    expect(safeProviderExecutionFamily(provider({
      provider_id: "codex",
      kind: "vendor_runtime",
      provider_role: "runtime_engine",
    }))).toBeNull();
  });

  it("retains the closed legacy Codex identity and hosted-text identity", () => {
    expect(safeProviderExecutionFamily(provider({
      provider_id: "codex",
      kind: "runtime_backend",
      provider_role: "runtime_engine",
    }))).toBe("native_agent");
    expect(safeProviderExecutionFamily(provider({
      kind: "hosted_api",
      provider_role: "model_provider",
    }))).toBe("hosted_text");
  });
});
