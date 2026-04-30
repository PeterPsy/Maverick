export function labelForType(type: string): string {
  return type.replace(/_/g, " ");
}

export function formatDate(value?: string): string {
  if (!value) return "Unknown";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat(undefined, {
    year: "numeric",
    month: "short",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  }).format(date);
}

export function confidenceLabel(value?: number): string {
  if (typeof value !== "number") return "n/a";
  return `${Math.round(value * 100)}%`;
}

export function truncate(value: string | undefined, max: number): string {
  const text = value || "";
  return text.length > max ? `${text.slice(0, max - 1)}...` : text;
}
