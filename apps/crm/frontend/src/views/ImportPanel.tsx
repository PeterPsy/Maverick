import { FormEvent } from 'react';
import { ImportPreview } from '../domain/types';

export function ImportPanel({ onSubmit, isSaving, preview }: { onSubmit: (event: FormEvent<HTMLFormElement>) => void; isSaving: boolean; preview: ImportPreview | null }) {
  return (
    <section className="crm-panel import-panel">
      <h2>Import</h2>
      <form onSubmit={onSubmit}>
        <label>
          Entity
          <select name="entity_type" defaultValue="contact">
            <option value="lead">Leads</option>
            <option value="account">Accounts</option>
            <option value="contact">Contacts</option>
            <option value="deal">Deals</option>
            <option value="activity">Activities</option>
            <option value="task">Tasks</option>
            <option value="note">Notes</option>
          </select>
        </label>
        <label>
          CSV
          <textarea name="csv" rows={10} placeholder="display_name,email&#10;Ada Lovelace,ada@example.com" />
        </label>
        <label>
          Column mapping
          <textarea name="column_mapping" rows={4} placeholder="Full Name=display_name&#10;Email=email&#10;Company=company" />
        </label>
        <div className="import-actions">
          <button type="submit" name="preview" disabled={isSaving}>Preview</button>
          <button type="submit" name="commit" disabled={isSaving}>Commit import</button>
        </div>
      </form>
      {preview ? (
        <div className="import-preview">
          <strong>Preview</strong>
          <span>{preview.row_count ?? 0} rows</span>
          {preview.counts ? <pre>{JSON.stringify(preview.counts, null, 2)}</pre> : null}
          {preview.errors?.length ? (
            <ul>
              {preview.errors.map((error) => (
                <li key={error.row}>Row {error.row}: {error.errors.join(', ')}</li>
              ))}
            </ul>
          ) : null}
        </div>
      ) : null}
    </section>
  );
}
