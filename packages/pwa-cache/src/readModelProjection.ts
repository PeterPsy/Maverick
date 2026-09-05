/** Closed field projections shared by app-owned display schemas and their host. */
export type DisplayRecord = Record<string, unknown>;
export function displayRecord(value: unknown): DisplayRecord | null {
  return value !== null && typeof value === "object" && !Array.isArray(value)
    && Object.getPrototypeOf(value) === Object.prototype ? value as DisplayRecord : null;
}
export function displayFields(value: unknown, fields: { text?: readonly string[]; number?: readonly string[]; boolean?: readonly string[] }): DisplayRecord | null {
  const record = displayRecord(value);
  if (!record) return null;
  const result: DisplayRecord = {};
  for (const [kind, names] of Object.entries(fields)) {
    for (const name of names) {
      const field = record[name];
      if (field === undefined || field === null) continue;
      if (typeof field !== (kind === "text" ? "string" : kind) || (kind === "number" && !Number.isFinite(field))) return null;
      result[name] = field;
    }
  }
  return result;
}
export function displayList<T>(value: unknown, project: (value: unknown) => T | null): T[] | null {
  if (!Array.isArray(value)) return null;
  const items = value.map(project);
  return items.some((item) => item === null) ? null : items as T[];
}
export function displayStrings(value: unknown): string[] | null {
  return displayList(value, (item) => typeof item === "string" ? item : null);
}
