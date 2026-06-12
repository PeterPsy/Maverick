import { ReactNode } from 'react';
import { CrmRecord } from '../api';
import { titleFor } from '../domain/routing';

export function textValue(record: Partial<CrmRecord>, key: string, fallback = '') {
  const value = record[key];
  return value === null || value === undefined ? fallback : String(value);
}

export function numericValue(record: Partial<CrmRecord>, key: string, fallback = '') {
  const value = record[key];
  return typeof value === 'number' || typeof value === 'string' ? String(value) : fallback;
}

export function SelectField({ label, name, defaultValue, children }: { label: string; name: string; defaultValue?: string; children: ReactNode }) {
  return (
    <label>
      {label}
      <select name={name} defaultValue={defaultValue || ''}>
        {children}
      </select>
    </label>
  );
}

export function RelatedRecordOptions({ records }: { records: CrmRecord[] }) {
  return (
    <>
      <option value="">None</option>
      {records.map((record) => (
        <option key={record.id} value={record.id}>
          {titleFor(record)}
        </option>
      ))}
    </>
  );
}
