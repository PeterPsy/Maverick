const FORBIDDEN_KEYS = new Set([
  "accesstoken",
  "apikey",
  "authorization",
  "clientsecret",
  "cookie",
  "credential",
  "credentials",
  "csrftoken",
  "idtoken",
  "jwt",
  "oauthtoken",
  "passphrase",
  "password",
  "privatekey",
  "refreshtoken",
  "secret",
  "sessiontoken",
  "setcookie",
  "signedurl",
  "token",
]);

const CREDENTIAL_KEY_SUFFIXES = ["apikey", "credential", "password", "privatekey", "secret", "token"];
const SIGNATURE_QUERY_KEYS = new Set(["googleaccessid", "sig", "signature", "xamzsignature", "xgoogsignature"]);
const CREDENTIAL_VALUE = /^(?:bearer\s+\S+|eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+|-----BEGIN [A-Z ]*PRIVATE KEY-----)/iu;
const MAX_SERIALIZATION_DEPTH = 32;

export function validatedPayloadSize(payload: unknown): number {
  assertPersistableValue(payload, 0, new Set<object>());
  const serialized = JSON.stringify(payload);
  if (serialized === undefined) {
    throw new TypeError("PWA cache payload is not JSON serializable.");
  }
  return new TextEncoder().encode(serialized).byteLength;
}

function assertPersistableValue(value: unknown, depth: number, ancestors: Set<object>): void {
  if (depth > MAX_SERIALIZATION_DEPTH) {
    throw new TypeError("PWA cache payload nesting is too deep.");
  }
  if (value === null || typeof value === "boolean" || typeof value === "number") {
    if (typeof value === "number" && !Number.isFinite(value)) {
      throw new TypeError("PWA cache payload contains a non-finite number.");
    }
    return;
  }
  if (typeof value === "string") {
    if (value.startsWith("blob:") || containsCredentialUrl(value)) {
      throw new TypeError("PWA cache payload contains an object or signed URL.");
    }
    if (CREDENTIAL_VALUE.test(value.trim())) {
      throw new TypeError("PWA cache payload contains credential-like material.");
    }
    return;
  }
  if (typeof value !== "object") {
    throw new TypeError("PWA cache payload contains a non-persistable value.");
  }
  if (ancestors.has(value)) {
    throw new TypeError("PWA cache payload contains a cycle.");
  }
  const nextAncestors = new Set(ancestors).add(value);
  if (Array.isArray(value)) {
    value.forEach((item) => assertPersistableValue(item, depth + 1, nextAncestors));
    return;
  }
  if (Object.getPrototypeOf(value) !== Object.prototype) {
    throw new TypeError("PWA cache payload must contain only plain objects and arrays.");
  }
  for (const [key, item] of Object.entries(value as Record<string, unknown>)) {
    if (isForbiddenKey(key)) {
      throw new TypeError("PWA cache payload contains credential-like material.");
    }
    assertPersistableValue(item, depth + 1, nextAncestors);
  }
}

function normalizeKey(key: string): string {
  return key.replace(/[^A-Za-z0-9]/g, "").toLowerCase();
}

function isForbiddenKey(key: string): boolean {
  const normalized = normalizeKey(key);
  return FORBIDDEN_KEYS.has(normalized)
    || CREDENTIAL_KEY_SUFFIXES.some((suffix) => normalized.endsWith(suffix));
}

function containsCredentialUrl(value: string): boolean {
  if (!value.includes("?") && !value.includes("&")) {
    return false;
  }
  try {
    const url = new URL(value, "https://maverick.invalid/");
    if (url.username || url.password) {
      return true;
    }
    for (const key of url.searchParams.keys()) {
      const normalized = normalizeKey(key);
      if (isForbiddenKey(key) || SIGNATURE_QUERY_KEYS.has(normalized)) {
        return true;
      }
    }
  } catch {
    return /(?:^|[?&])[^=]*(?:token|secret|signature|credential|password|api[_-]?key)=/iu.test(value);
  }
  return false;
}
