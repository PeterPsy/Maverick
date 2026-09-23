export function formatMoney(minor: number, compact = false) {
  return new Intl.NumberFormat('it-IT', {
    style: 'currency',
    currency: 'EUR',
    maximumFractionDigits: compact ? 0 : 2,
    notation: compact && minor >= 100_000_00 ? 'compact' : 'standard'
  }).format((minor || 0) / 100);
}

export function localDate(value: string) {
  if (!value) return '';
  return new Intl.DateTimeFormat('it-IT', { day: 'numeric', month: 'short' }).format(new Date(`${value}T12:00:00`));
}

export function todayIso() {
  const now = new Date();
  const offset = now.getTimezoneOffset() * 60_000;
  return new Date(now.getTime() - offset).toISOString().slice(0, 10);
}

export function daysFromToday(value: string) {
  if (!value) return Number.POSITIVE_INFINITY;
  const start = new Date(`${todayIso()}T12:00:00`).getTime();
  const target = new Date(`${value}T12:00:00`).getTime();
  return Math.round((target - start) / 86_400_000);
}

export function dueLabel(value: string) {
  const days = daysFromToday(value);
  if (!Number.isFinite(days)) return 'Nessuna data';
  if (days < 0) return `${Math.abs(days)}g in ritardo`;
  if (days === 0) return 'Oggi';
  if (days === 1) return 'Domani';
  return localDate(value);
}
