import { describe, expect, it } from "vitest";
import {
  BrowserStorageQuotaAdapter,
  LOCAL_PERSISTENCE_POLICY_REVISION,
  clampPrivateAccessLease,
  deriveLocalPersistencePolicy,
  isAgenticControlPlaneResource,
  type MaverickDataClass,
  type ResourceCachePolicy,
} from "../src";
import { cacheEntryKey, validatePrincipal, validatedPayloadSize } from "../src/testing";

function policy(dataClass: MaverickDataClass, overrides: Partial<ResourceCachePolicy<unknown>> = {}): ResourceCachePolicy<unknown> {
  return {
    dataClass,
    expiryTtlMs: 60_000,
    freshTtlMs: 1_000,
    maxEntryBytes: 1_024,
    maxScopeBytes: 8_192,
    policyRevision: LOCAL_PERSISTENCE_POLICY_REVISION,
    provenance: "app_reference",
    schemaRevision: "records.v1",
    sanitize: (value) => value,
    ...overrides,
  };
}

describe("PWA cache scope and policy", () => {
  it("requires every principal and resource scope component", () => {
    expect(() => validatePrincipal({ userId: "", workspaceId: "default", appId: "docs" })).toThrow(/userId/);
    expect(() => cacheEntryKey({
      userId: "user-a",
      workspaceId: "default",
      appId: "docs",
      resource: "",
      policyRevision: LOCAL_PERSISTENCE_POLICY_REVISION,
      schemaRevision: "records.v1",
    }, "one")).toThrow(/resource/);
  });

  it("uses collision-safe keys across every mandatory scope dimension", () => {
    const base = {
      userId: "user-a",
      workspaceId: "default",
      appId: "docs",
      resource: "records",
      policyRevision: LOCAL_PERSISTENCE_POLICY_REVISION,
      schemaRevision: "records.v1",
    };
    const keys = new Set([
      cacheEntryKey(base, "one"),
      cacheEntryKey({ ...base, userId: "user-b" }, "one"),
      cacheEntryKey({ ...base, workspaceId: "other" }, "one"),
      cacheEntryKey({ ...base, appId: "mail" }, "one"),
      cacheEntryKey({ ...base, resource: "other" }, "one"),
      cacheEntryKey({ ...base, schemaRevision: "records.v2" }, "one"),
      cacheEntryKey(base, "one", 4),
    ]);
    expect(keys.size).toBe(7);
  });

  it("derives only deny, session, or cache from the canonical mapping", () => {
    expect(deriveLocalPersistencePolicy("docs", "records", policy("public"))).toBe("cache");
    expect(deriveLocalPersistencePolicy("docs", "records", policy("workspace_internal"))).toBe("session");
    expect(deriveLocalPersistencePolicy("docs", "records", policy("workspace_internal", { cacheApproved: true }))).toBe("cache");
    expect(deriveLocalPersistencePolicy("chat", "messages", policy("personal_data", { cacheApproved: true }))).toBe("session");
    expect(deriveLocalPersistencePolicy("chat", "messages", policy("personal_data", { cacheApproved: true, privacyApproved: true }))).toBe("cache");
    expect(deriveLocalPersistencePolicy("mail", "threads", policy("regulated_or_customer_data", {
      cacheApproved: true,
      privacyApproved: true,
      regulatedAllowlisted: true,
    }))).toBe("cache");
  });

  it("fails closed for unknown revisions, provenance, classifications, and invalid budgets", () => {
    expect(deriveLocalPersistencePolicy("docs", "records", policy("public", { policyRevision: "unknown" }))).toBe("deny");
    expect(deriveLocalPersistencePolicy("docs", "records", policy("public", { provenance: "unknown" as never }))).toBe("deny");
    expect(deriveLocalPersistencePolicy("docs", "records", policy("unclassified"))).toBe("deny");
    expect(deriveLocalPersistencePolicy("docs", "records", policy("public", { maxEntryBytes: 0 }))).toBe("deny");
  });

  it("keeps the agentic control plane denylisted even under public/cache claims", () => {
    for (const resource of [
      "effective-capabilities",
      "certificates",
      "provider-binding",
      "egress-authorization",
      "pending-tool-call",
      "secret-grant",
      "revocations",
    ]) {
      expect(isAgenticControlPlaneResource("agents", resource)).toBe(true);
      expect(deriveLocalPersistencePolicy("agents", resource, policy("public", { cacheApproved: true }))).toBe("deny");
    }
    expect(deriveLocalPersistencePolicy("core-control-plane", "anything", policy("public"))).toBe("deny");
  });

  it("uses canonical app and provenance decisions instead of resource-name heuristics", () => {
    for (const resource of ["models", "configuration", "tool-results", "provider-catalog"]) {
      expect(isAgenticControlPlaneResource("agents", resource, "app_reference")).toBe(true);
      expect(deriveLocalPersistencePolicy("agents", resource, policy("public", { cacheApproved: true }))).toBe("deny");
    }
    expect(isAgenticControlPlaneResource("docs", "harmless-name", "tool_result")).toBe(true);
    expect(deriveLocalPersistencePolicy("docs", "harmless-name", policy("public", {
      provenance: "tool_result",
    }))).toBe("deny");
  });

  it("bounds private access leases to fifteen minutes", () => {
    const now = 10_000;
    expect(clampPrivateAccessLease(now + 60 * 60_000, now)).toEqual({ issuedAt: now, expiresAt: now + 15 * 60_000 });
    expect(clampPrivateAccessLease(now, now)).toBeNull();
  });
});

describe("browser quota policy", () => {
  it("fails closed when the browser cannot provide a quota estimate", async () => {
    const adapter = new BrowserStorageQuotaAdapter();
    await expect(adapter.canWrite(1)).resolves.toBe(false);
  });
});

describe("persistent payload guard", () => {
  it("accepts bounded plain JSON", () => {
    expect(validatedPayloadSize({ rows: [{ id: "one", value: 2 }] })).toBeGreaterThan(0);
  });

  it("rejects secrets, signed URLs, object URLs, and non-plain objects", () => {
    expect(() => validatedPayloadSize({ access_token: "secret" })).toThrow(/credential-like/);
    expect(() => validatedPayloadSize({ github_token: "secret" })).toThrow(/credential-like/);
    expect(() => validatedPayloadSize({ href: "https://example.test/callback?access_token=secret" })).toThrow(/signed URL|credential/i);
    expect(() => validatedPayloadSize({ href: "https://files.test/a?X-Amz-Signature=secret" })).toThrow(/signed URL/);
    expect(() => validatedPayloadSize({ href: "blob:https://maverick.test/id" })).toThrow(/object or signed URL/);
    expect(() => validatedPayloadSize({ when: new Date() })).toThrow(/plain objects/);
    expect(() => validatedPayloadSize({ content: "Bearer private-token" })).toThrow(/credential-like/);
  });
});
