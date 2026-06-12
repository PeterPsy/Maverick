import { callBackend } from '../api';
import { ComposerState } from './types';
import { CrmActionContext } from './actionContext';
import { createActions, entityFilterForEntity, updateActions, viewForEntity } from './routing';

export function useCrmComposerActions({
  refresh,
  refreshRecords,
  setComposer,
  setError,
  setIsSaving,
  setRecordEntityFilter,
  setView
}: CrmActionContext) {
  async function saveComposer(state: Exclude<ComposerState, null>, values: Record<string, unknown>) {
    setIsSaving(true);
    setError('');
    try {
      const action = state.mode === 'create' ? createActions[state.entity] : updateActions[state.entity];
      const body = state.mode === 'edit' ? { ...values, id: state.record.id } : values;
      await callBackend({ action, ...body });
      setView(viewForEntity(state.entity));
      setRecordEntityFilter(entityFilterForEntity(state.entity));
      setComposer(null);
      await refresh();
      await refreshRecords('');
    } catch (saveError) {
      setError(saveError instanceof Error ? saveError.message : 'Unable to save record.');
    } finally {
      setIsSaving(false);
    }
  }

  return { saveComposer };
}
