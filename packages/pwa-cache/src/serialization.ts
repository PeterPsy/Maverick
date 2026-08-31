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
const CREDENTIAL_VALUES = [
  /(?:^|[\s:])(?:bearer|basic|digest|token)\s+\S+/iu,
  /(?:^|[^A-Za-z0-9_-])eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+(?=$|[^A-Za-z0-9_-])/u,
  /-----BEGIN [A-Z ]*PRIVATE KEY-----/iu,
  /(?:^|[^A-Za-z0-9_])(?:sk|pk|rk|ghp|gho|ghu|ghs|ghr|github_pat)_[A-Za-z0-9_=-]{16,}(?=$|[^A-Za-z0-9_=-])/u,
  /(?:^|[^A-Za-z0-9_-])(?:sk-|glpat-|npm_|xox[baprs]-)[A-Za-z0-9_-]{16,}(?=$|[^A-Za-z0-9_-])/u,
  /(?:^|[^A-Z0-9])(?:AKIA|ASIA)[A-Z0-9]{16}(?=$|[^A-Z0-9])/u,
  /(?:^|[^A-Za-z0-9_-])(?:AIza[A-Za-z0-9_-]{20,}|ya29\.[A-Za-z0-9_-]{20,})(?=$|[^A-Za-z0-9_-])/u,
];
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
    const normalized = value.trim();
    if (isObjectUrl(normalized) || containsCredentialUrl(normalized)) {
      throw new TypeError("PWA cache payload contains an object or signed URL.");
    }
    if (containsCredentialMaterial(normalized)) {
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
    // Generic credential material is checked separately.
  }
  return false;
}

function isObjectUrl(value: string): boolean {
  return /^blob\s*:/iu.test(value);
}

function containsCredentialMaterial(value: string): boolean {
  if (CREDENTIAL_VALUES.some((pattern) => pattern.test(value))) {
    return true;
  }
  for (const match of value.matchAll(
    /(?:^|[^A-Za-z0-9_.-])["']?([A-Za-z][A-Za-z0-9_.-]{0,63})["']?\s*[:=]\s*(?=\S)/gu,
  )) {
    const key = match[1] ?? "";
    if (isForbiddenKey(key) || SIGNATURE_QUERY_KEYS.has(normalizeKey(key))) {
      return true;
    }
  }
  return false;
}
