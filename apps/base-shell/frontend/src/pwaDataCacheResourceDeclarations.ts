import { sanitizeChatReadModel } from '../../../chat/frontend/src/pwaReadModel';
import { sanitizeCrmReadModel } from '../../../crm/frontend/src/pwaReadModel';
import { sanitizeMailReadModel } from '../../../mail/frontend/src/pwaReadModel';
import { sanitizeBootstrapReadModel } from '../../../fitness-coach/frontend/src/bootstrapCache';
import { sanitizeThumbPreviewEntry } from '../../../fitness-coach/frontend/src/mediaThumbPreviewCache';
import { sanitizeCalendarReadModel } from '../../../calendar/frontend/src/pwaReadModel';
import {
  LOCAL_PERSISTENCE_POLICY_REVISION,
  deriveLocalPersistencePolicy,
  type MaverickDataClass,
  type MaverickProvenance,
  type ResourceCachePolicy,
} from "@maverick/pwa-cache";
import runtimeResources from "./pwaDataCacheResourceDeclarations.v1.json";

const RUNTIME_RESOURCE_SCHEMA = "maverick.pwa-data-cache-runtime-resources.v1";
const DATA_CLASSES = new Set<MaverickDataClass>([
  "public",
  "workspace_internal_fake",
  "workspace_internal",
  "personal_data",
  "regulated_or_customer_data",
  "credential_or_secret",
  "host_operational_metadata",
  "unclassified",
]);
const PROVENANCE_VALUES = new Set<MaverickProvenance>([
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

export type ResourceDeclaration = {
  aliases: readonly string[];
  policy: ResourceCachePolicy<unknown>;
};

export const RESOURCE_DECLARATIONS = buildResourceDeclarations();

function buildResourceDeclarations(): Readonly<Record<string, Readonly<Record<string, ResourceDeclaration>>>> {
  if (runtimeResources.schema !== RUNTIME_RESOURCE_SCHEMA
      || runtimeResources.policy_revision !== LOCAL_PERSISTENCE_POLICY_REVISION
      || !sameStringSet(runtimeResources.canonical_data_classes, DATA_CLASSES)) {
    throw new TypeError("PWA data-cache runtime resource manifest has an unsupported policy schema.");
  }
  const declarations: Record<string, Record<string, ResourceDeclaration>> = {};
  for (const record of runtimeResources.resources) {
    const dataClass = enumValue(record.canonical_data_class, DATA_CLASSES, "data class");
    const provenance = enumValue(record.provenance, PROVENANCE_VALUES, "provenance");
    const policy: ResourceCachePolicy<unknown> = {
      allowStale: true,
      cacheApproved: record.cache_approved,
      dataClass,
      expiryTtlMs: positiveInteger(record.expiry_ttl_ms, "expiry TTL"),
      freshTtlMs: nonNegativeInteger(record.fresh_ttl_ms, "fresh TTL"),
      maxEntryBytes: positiveInteger(record.max_entry_bytes, "entry budget"),
      maxScopeBytes: positiveInteger(record.max_scope_bytes, "scope budget"),
      policyRevision: LOCAL_PERSISTENCE_POLICY_REVISION,
      privacyApproved: record.privacy_approved,
      provenance,
      regulatedAllowlisted: record.regulated_allowlisted,
      revalidateOnRead: "always",
      sanitize: record.app_id === 'calendar' ? sanitizeCalendarReadModel
        : record.app_id === 'fitness-coach' ? (value) => sanitizeBootstrapReadModel(value) ?? sanitizeThumbPreviewEntry(value)
        : record.app_id === 'chat' ? sanitizeChatReadModel
        : record.app_id === 'crm' ? sanitizeCrmReadModel
        : record.app_id === 'mail' ? sanitizeMailReadModel
        : sanitizeStructuredReadModel,
      schemaRevision: boundedText(record.schema_revision, "schema revision"),
    };
    const appId = boundedText(record.app_id, "app id");
    const resource = boundedText(record.resource, "resource");
    if (deriveLocalPersistencePolicy(appId, resource, policy) !== record.local_persistence_policy) {
      throw new TypeError(`PWA data-cache runtime policy mismatch for ${appId}/${resource}.`);
    }
    const appDeclarations = declarations[appId] ??= {};
    if (appDeclarations[resource]) {
      throw new TypeError(`Duplicate PWA data-cache runtime resource ${appId}/${resource}.`);
    }
    appDeclarations[resource] = Object.freeze({
      aliases: Object.freeze(record.aliases.map((alias) => boundedText(alias, "resource alias"))),
      policy: Object.freeze(policy),
    });
  }
  return Object.freeze(Object.fromEntries(
    Object.entries(declarations).map(([appId, resources]) => [appId, Object.freeze(resources)]),
  ));
}

function sameStringSet(values: readonly string[], expected: ReadonlySet<string>): boolean {
  return values.length === expected.size && new Set(values).size === expected.size
    && values.every((value) => expected.has(value));
}

function sanitizeStructuredReadModel(payload: unknown): unknown | null {
  if (!payload || typeof payload !== "object"
      || (!Array.isArray(payload) && Object.getPrototypeOf(payload) !== Object.prototype)) {
    return null;
  }
  return isStructuredJson(payload, 0, new Set()) ? payload : null;
}

function isStructuredJson(value: unknown, depth: number, ancestors: Set<object>): boolean {
  if (depth > 32) return false;
  if (value === null || typeof value === "string" || typeof value === "boolean") return true;
  if (typeof value === "number") return Number.isFinite(value);
  if (!value || typeof value !== "object" || ancestors.has(value)) return false;
  if (!Array.isArray(value) && Object.getPrototypeOf(value) !== Object.prototype) return false;
  const next = new Set(ancestors).add(value);
  return (Array.isArray(value) ? value : Object.values(value))
    .every((item) => isStructuredJson(item, depth + 1, next));
}

function enumValue<T extends string>(value: string, allowed: ReadonlySet<T>, label: string): T {
  if (!allowed.has(value as T)) throw new TypeError(`Invalid PWA data-cache ${label}.`);
  return value as T;
}

function boundedText(value: string, label: string): string {
  if (!value || value !== value.trim() || value.length > 128) {
    throw new TypeError(`Invalid PWA data-cache ${label}.`);
  }
  return value;
}

function positiveInteger(value: number, label: string): number {
  if (!Number.isSafeInteger(value) || value <= 0) throw new TypeError(`Invalid PWA data-cache ${label}.`);
  return value;
}

function nonNegativeInteger(value: number, label: string): number {
  if (!Number.isSafeInteger(value) || value < 0) throw new TypeError(`Invalid PWA data-cache ${label}.`);
  return value;
}
