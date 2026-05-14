import type { DynamicViewSnapshotMode } from '../types';

const DATE_FORMATTER = new Intl.DateTimeFormat(undefined, {
  dateStyle: 'medium',
  timeStyle: 'short'
});

export function formatDynamicViewDate(value?: string) {
  if (!value) return 'Not available';
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : DATE_FORMATTER.format(date);
}

export function snapshotModeLabel(value: DynamicViewSnapshotMode) {
  return value === 'live' ? 'Live' : 'Snapshot';
}
