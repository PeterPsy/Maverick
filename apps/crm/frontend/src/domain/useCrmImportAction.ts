import type { FormEvent } from 'react';
import { callBackend } from '../api';
import { CrmActionContext } from './actionContext';
import { ImportPreview } from './types';
import { parseColumnMapping } from './routing';

export function useCrmImportAction({ refresh, setError, importPreview, setImportPreview, setIsSaving }: CrmActionContext) {
  async function handleImport(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const submitter = (event.nativeEvent as SubmitEvent).submitter as HTMLButtonElement | null;
    const planning = submitter?.name !== 'commit';
    setIsSaving(true); setError('');
    try {
      const format = String(form.get('format') || 'csv');
      const content = String(form.get('content') || '');
      const source: Record<string, unknown> = { format, source_id: String(form.get('source_id') || '') };
      if (format === 'csv') Object.assign(source, { entity_type: form.get('entity_type'), csv: content, column_mapping: parseColumnMapping(form.get('column_mapping')) });
      else {
        const parsed = JSON.parse(content);
        if (format === 'crm_export') source.export = parsed.export || parsed;
        else if (format === 'versy') source.tables = parsed.tables || parsed;
        else Object.assign(source, { entity_type: form.get('entity_type'), rows: Array.isArray(parsed) ? parsed : parsed.rows });
      }
      if (!planning && !importPreview?.plan_token) throw new Error('Preview this source before applying it.');
      const result = await callBackend<ImportPreview>({ action: planning ? 'crm.import_plan' : 'crm.import_apply', source, conflict_policy: form.get('conflict_policy'), ...(planning ? {} : { plan_token: importPreview?.plan_token }) });
      setImportPreview(result);
      if (result.committed) await refresh();
    } catch (failure) { setError(failure instanceof Error ? failure.message : 'Import failed.'); }
    finally { setIsSaving(false); }
  }
  return { handleImport };
}
