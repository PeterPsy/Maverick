import { describe, expect, it } from 'vitest';
import { formatStorageTimestamp } from './storageMeta';

describe('formatStorageTimestamp', () => {
  it('formats a storage timestamp with date and time', () => {
    const expected = new Intl.DateTimeFormat('en-US', {
      dateStyle: 'short',
      timeStyle: 'short',
      timeZone: 'UTC'
    }).format(new Date('2026-06-04T14:05:00Z'));
    expect(formatStorageTimestamp('2026-06-04T14:05:00Z', { locale: 'en-US', timeZone: 'UTC' })).toBe(expected);
  });

  it('returns the fallback for missing or invalid timestamps', () => {
    expect(formatStorageTimestamp('', { fallback: 'Uploaded' })).toBe('Uploaded');
    expect(formatStorageTimestamp('not-a-date', { fallback: 'Generated' })).toBe('Generated');
  });
});
