import {
  LOCAL_PERSISTENCE_POLICY_REVISION,
  type AccessLease,
  type LocalPersistencePolicy,
  type MaverickDataClass,
  type ResourceCachePolicy,
} from "./types";

export const PRIVATE_ACCESS_LEASE_MAX_MS = 15 * 60 * 1_000;

const CONTROL_PLANE_TERMS = [
  "admission",
  "authority",
  "capability",
  "capabilities",
  "certificate",
  "certificates",
  "confirmation",
  "egress",
  "pending-tool-call",
  "preflight",
  "provider-binding",
  "provider-profile",
  "provider-state",
  "proposal",
  "recovery-required",
  "revocation",
  "revocations",
  "secret-grant",
];

const KNOWN_PROVENANCE = new Set([
  "platform_instruction",
  "runtime_context",
  "runtime_capabilities",
  "workspace_instruction",
  "agent_instruction",
  "skill_fragment",
  "finalization_instruction",
  "prompt",
  "user_input",
  "orchestration_context",
  "governed_context",
  "skill",
  "attachment",
  "app_reference",
  "tool_schema",
  "tool_result",
  "provider_state",
]);

export function deriveLocalPersistencePolicy<T>(
  appId: string,
  resource: string,
  policy: ResourceCachePolicy<T>,
): LocalPersistencePolicy {
  if (policy.policyRevision !== LOCAL_PERSISTENCE_POLICY_REVISION || isAgenticControlPlaneResource(appId, resource)) {
    return "deny";
  }
  if (!KNOWN_PROVENANCE.has(policy.provenance) || !validPolicyBounds(policy)) {
    return "deny";
  }
  switch (policy.dataClass) {
    case "public":
      return "cache";
    case "workspace_internal_fake":
    case "workspace_internal":
      return policy.cacheApproved ? "cache" : "session";
    case "personal_data":
      return policy.cacheApproved && policy.privacyApproved ? "cache" : "session";
    case "regulated_or_customer_data":
      return policy.cacheApproved && policy.privacyApproved && policy.regulatedAllowlisted ? "cache" : "deny";
    case "credential_or_secret":
    case "host_operational_metadata":
    case "unclassified":
    default:
      return "deny";
  }
}

export function isAgenticControlPlaneResource(appId: string, resource: string): boolean {
  const normalizedApp = normalizePolicyName(appId);
  if (normalizedApp === "core-control-plane") {
    return true;
  }
  const normalizedResource = normalizePolicyName(resource);
  return CONTROL_PLANE_TERMS.some((term) =>
    normalizedResource === term
    || normalizedResource.startsWith(`${term}-`)
    || normalizedResource.endsWith(`-${term}`)
    || normalizedResource.includes(`-${term}-`),
  );
}

export function hasValidAccessLease(
  dataClass: MaverickDataClass,
  lease: AccessLease | undefined,
  now: number,
): boolean {
  if (dataClass === "public") {
    return true;
  }
  if (!lease || !Number.isFinite(lease.issuedAt) || !Number.isFinite(lease.expiresAt)) {
    return false;
  }
  if (lease.issuedAt > now || lease.expiresAt <= now || lease.expiresAt - lease.issuedAt > PRIVATE_ACCESS_LEASE_MAX_MS) {
    return false;
  }
  return true;
}

export function clampPrivateAccessLease(sessionExpiresAt: number, now = Date.now()): AccessLease | null {
  if (!Number.isFinite(sessionExpiresAt) || sessionExpiresAt <= now) {
    return null;
  }
  return { issuedAt: now, expiresAt: Math.min(sessionExpiresAt, now + PRIVATE_ACCESS_LEASE_MAX_MS) };
}

function validPolicyBounds<T>(policy: ResourceCachePolicy<T>): boolean {
  return Number.isFinite(policy.freshTtlMs)
    && policy.freshTtlMs >= 0
    && Number.isFinite(policy.expiryTtlMs)
    && policy.expiryTtlMs > 0
    && policy.expiryTtlMs >= policy.freshTtlMs
    && Number.isFinite(policy.maxEntryBytes)
    && policy.maxEntryBytes > 0
    && Number.isFinite(policy.maxScopeBytes)
    && policy.maxScopeBytes >= policy.maxEntryBytes
    && typeof policy.sanitize === "function";
}

function normalizePolicyName(value: string): string {
  return String(value || "")
    .trim()
    .replace(/([a-z0-9])([A-Z])/g, "$1-$2")
    .replace(/[^A-Za-z0-9]+/g, "-")
    .replace(/^-|-$/g, "")
    .toLowerCase();
}
