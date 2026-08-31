import {
  LOCAL_PERSISTENCE_POLICY_REVISION,
  type AccessLease,
  type LocalPersistencePolicy,
  type MaverickDataClass,
  type ResourceCachePolicy,
} from "./types";

export const PRIVATE_ACCESS_LEASE_MAX_MS = 15 * 60 * 1_000;

const AGENTIC_CONTROL_PLANE_APP_IDS = new Set([
  "agents",
  "core-control-plane",
  "models",
  "providers",
]);

const AGENTIC_CONTROL_PLANE_PROVENANCE = new Set([
  "platform_instruction",
  "runtime_context",
  "runtime_capabilities",
  "workspace_instruction",
  "agent_instruction",
  "skill_fragment",
  "finalization_instruction",
  "prompt",
  "orchestration_context",
  "governed_context",
  "skill",
  "tool_schema",
  "tool_result",
  "provider_state",
]);

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
  if (policy.policyRevision !== LOCAL_PERSISTENCE_POLICY_REVISION
      || isAgenticControlPlaneResource(appId, resource, policy.provenance)) {
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

export function isAgenticControlPlaneResource(
  appId: string,
  _resource: string,
  provenance?: ResourceCachePolicy<unknown>["provenance"],
): boolean {
  const normalizedApp = normalizePolicyName(appId);
  return AGENTIC_CONTROL_PLANE_APP_IDS.has(normalizedApp)
    || (typeof provenance === "string" && AGENTIC_CONTROL_PLANE_PROVENANCE.has(provenance));
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
  return Number.isSafeInteger(policy.freshTtlMs)
    && policy.freshTtlMs >= 0
    && Number.isSafeInteger(policy.expiryTtlMs)
    && policy.expiryTtlMs > 0
    && policy.expiryTtlMs >= policy.freshTtlMs
    && Number.isSafeInteger(policy.maxEntryBytes)
    && policy.maxEntryBytes > 0
    && Number.isSafeInteger(policy.maxScopeBytes)
    && policy.maxScopeBytes >= policy.maxEntryBytes
    && typeof policy.schemaRevision === "string"
    && policy.schemaRevision.trim().length > 0
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
