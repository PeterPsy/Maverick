import type { FormEvent } from 'react';
import { callBackend } from '../api';
import { CrmActionContext } from './actionContext';
import { ImportPreview } from './types';
import { parseColumnMapping } from './routing';

export function useCrmImportAction({ refresh, setError, setImportPreview, setIsSaving }: CrmActionContext) {
  async function handleImport(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const submitter = (event.nativeEvent as SubmitEvent).submitter as HTMLButtonElement | null;
    const action = submitter?.name === 'preview' ? 'crm.import_preview' : 'crm.import_commit';
    setIsSaving(true);
    setError('');
    try {
      const result = await callBackend<ImportPreview>({
        action,
        entity_type: form.get('entity_type'),
        csv: form.get('csv'),
        column_mapping: parseColumnMapping(form.get('column_mapping'))
      });
      if (action === 'crm.import_preview') {
        setImportPreview(result);
      } else {
        setImportPreview(null);
        event.currentTarget.reset();
        await refresh();
      }
    } catch (importError) {
      setError(importError instanceof Error ? importError.message : 'Import failed.');
    } finally {
      setIsSaving(false);
    }
  }

  return { handleImport };
}
