import { FormEvent, useEffect, useState } from 'react';
import { ImportPreview } from '../domain/types';
import { allEntities, label } from '../domain/vnext';

export function ImportPanel({ onSubmit, isSaving, preview }: { onSubmit: (event: FormEvent<HTMLFormElement>) => void; isSaving: boolean; preview: ImportPreview | null }) {
  const [format, setFormat] = useState('csv');
  const [content, setContent] = useState('');
  const [dirty, setDirty] = useState(true);
  const [fileError, setFileError] = useState('');
  useEffect(() => { if (preview?.plan_token) setDirty(false); }, [preview]);
  return <section className="vn-page"><header className="vn-page-heading"><div><small>BRING YOUR CONTEXT</small><h1>Import workspace data</h1><p>Map, simulate, review, then apply. Existing data is never replaced without an explicit conflict policy.</p></div></header>
    <div className="vn-overview-grid"><form className="vn-surface vn-import-form" onSubmit={onSubmit} onChange={() => setDirty(true)}>
      <div className="vn-form-grid"><label>Source format<select name="format" value={format} onChange={(event) => setFormat(event.target.value)}><option value="csv">CSV</option><option value="json">JSON rows</option><option value="crm_export">Maverick CRM export</option><option value="versy">External CRM table export (Versy adapter)</option></select></label>
      <label>Source identity<input name="source_id" defaultValue="manual-import" required placeholder="e.g. customer-system-production" /></label></div>
      <p className="vn-hint">Reuse the same source identity on subsequent imports to prevent duplicates. This is not a credential.</p>
      {format === 'csv' || format === 'json' ? <label>Entity<select name="entity_type" defaultValue="contact">{allEntities.map((entity) => <option value={entity} key={entity}>{label(entity)}</option>)}</select></label> : null}
      <label>Conflict policy<select name="conflict_policy" key={format} defaultValue={format === 'crm_export' ? 'overwrite' : 'skip'}><option value="skip">Skip matching records</option><option value="duplicate">Create separate records (idempotent per source)</option><option value="fill_empty">Fill empty fields only</option><option value="overwrite">Overwrite supplied fields</option><option value="manual">Stop for manual review</option></select></label>
      <label>Upload CSV or JSON<input type="file" accept=".csv,.json,text/csv,application/json" onChange={(event) => { const file = event.target.files?.[0]; setFileError(''); if (!file) return; if (file.size > 8_000_000) { setFileError('Maximum source size is 8 MB. Split large migrations into ordered batches.'); return; } void file.text().then((text) => { setContent(text); setDirty(true); }).catch(() => setFileError('Unable to read file.')); }} /></label>
      <label>Source content<textarea name="content" rows={10} required value={content} onChange={(event) => setContent(event.target.value)} placeholder={format === 'csv' ? 'id,display_name,email\n1,Ada Lovelace,ada@example.com' : 'Paste a JSON export here'} /></label>
      {format === 'csv' ? <label>Column mapping<textarea name="column_mapping" rows={3} placeholder="Full Name=display_name\nEmail=email" /></label> : null}
      {fileError ? <p className="crm-alert" role="alert">{fileError}</p> : null}
      <div className="vn-actions"><button type="submit" name="preview" disabled={isSaving}>1. Simulate import</button><button className="vn-primary" type="submit" name="commit" disabled={isSaving || dirty || !preview?.ok || !preview.plan_token || preview.committed}>2. Apply reviewed import</button></div>
    </form><section className="vn-surface vn-import-report" aria-live="polite"><h2>{preview?.committed ? 'Import committed' : 'Review before writing'}</h2>
      {isSaving ? <p>Validating the import…</p> : null}
      {!preview ? <p className="vn-hint">Simulation uses an isolated copy and performs the same relationship and field validation as the real import. No CRM records are written.</p> : <>
        <p>{preview.row_count || 0} source records</p><div className="vn-report-counts"><span>{preview.created_count || 0} new</span><span>{preview.updated_count || 0} updated</span><span>{preview.skipped_count || 0} skipped</span></div>
        {dirty && !preview.committed ? <p className="vn-hint">Source changed. Run the simulation again.</p> : null}
        {preview.errors?.length ? <ul>{preview.errors.map((error, index) => <li key={index}>Row {error.row}: {error.errors.join(', ')}</li>)}</ul> : null}
        {preview.warnings?.map((warning, index) => <p className="vn-hint" key={index}>{warning}</p>)}
        {preview.job_id ? <p>Report ID: <code>{preview.job_id}</code></p> : null}
        {preview.ok && !preview.committed ? <p className="vn-hint">All rows validated. The server will reject this plan if the source or CRM changes before application.</p> : null}
      </>}
      <p className="vn-hint">Up to 2,000 records/relationships per atomic batch. Any invalid row rolls back the entire batch. Imported campaign state never authorizes delivery.</p>
    </section></div>
  </section>;
}
