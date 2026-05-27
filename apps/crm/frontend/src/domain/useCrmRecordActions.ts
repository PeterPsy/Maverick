import { PipelineStage, callBackend } from '../api';
import { CrmActionContext } from './actionContext';
import { MutatedRecordPayload } from './types';

export function useCrmRecordActions({
  actionDialog,
  bulkSelection,
  refresh,
  refreshPipelineBoard,
  selected,
  setActionDialog,
  setBulkSelection,
  setError,
  setIsSaving,
  setSelected
}: CrmActionContext) {
  async function mutateSelectedRecord(action: string, extras: Record<string, unknown> = {}, closeAfter = false): Promise<boolean> {
    if (!selected) return false;
    setIsSaving(true);
    setError('');
    try {
      const result = await callBackend<MutatedRecordPayload>({
        action,
        entity_type: selected.entity,
        id: selected.record.id,
        ...extras
      });
      if (closeAfter) {
        setSelected(null);
      } else if (result.record) {
        setSelected({ entity: selected.entity, record: result.record });
      }
      await refresh();
      return true;
    } catch (mutationError) {
      setError(mutationError instanceof Error ? mutationError.message : 'Unable to update record.');
      return false;
    } finally {
      setIsSaving(false);
    }
  }

  function tagSelectedRecord() {
    if (!selected) return;
    setActionDialog({ kind: 'record-tag' });
  }

  async function submitRecordTag(tag: string): Promise<boolean> {
    if (!tag.trim()) return false;
    return mutateSelectedRecord('crm.tag_record', { tag: tag.trim() });
  }

  async function convertSelectedLead() {
    if (!selected || selected.entity !== 'lead') return;
    setIsSaving(true);
    setError('');
    try {
      await callBackend({ action: 'crm.convert_lead', lead_id: selected.record.id });
      setSelected(null);
      await refresh();
    } catch (convertError) {
      setError(convertError instanceof Error ? convertError.message : 'Unable to convert lead.');
    } finally {
      setIsSaving(false);
    }
  }

  async function moveDeal(dealId: string, stageId: string) {
    setIsSaving(true);
    setError('');
    try {
      await callBackend({ action: 'crm.move_deal', id: dealId, stage_id: stageId });
      await refresh();
      await refreshPipelineBoard();
    } catch (moveError) {
      setError(moveError instanceof Error ? moveError.message : 'Unable to move deal.');
    } finally {
      setIsSaving(false);
    }
  }

  function configureStage(stage?: PipelineStage) {
    setActionDialog({ kind: 'pipeline-stage', stage });
  }

  async function deletePipelineStage(stage: PipelineStage) {
    if (!window.confirm(`Delete ${stage.name} pipeline stage? Deals in this stage will move to the nearest previous stage.`)) return;
    setIsSaving(true);
    setError('');
    try {
      await callBackend({ action: 'crm.delete_pipeline_stage', id: stage.id, pipeline_id: stage.pipeline_id || 'pipeline_default' });
      await refresh();
      await refreshPipelineBoard();
    } catch (stageError) {
      setError(stageError instanceof Error ? stageError.message : 'Unable to delete pipeline stage.');
    } finally {
      setIsSaving(false);
    }
  }

  async function submitPipelineStage(values: { name: string; probability: number }): Promise<boolean> {
    if (actionDialog?.kind !== 'pipeline-stage') return false;
    const stage = actionDialog.stage;
    if (!values.name.trim()) return false;
    setIsSaving(true);
    setError('');
    try {
      await callBackend({
        action: stage ? 'crm.update_pipeline_stage' : 'crm.create_pipeline_stage',
        id: stage?.id,
        pipeline_id: stage?.pipeline_id || 'pipeline_default',
        name: values.name.trim(),
        position: stage?.position,
        probability: values.probability
      });
      await refresh();
      await refreshPipelineBoard();
      return true;
    } catch (stageError) {
      setError(stageError instanceof Error ? stageError.message : 'Unable to save pipeline stage.');
      return false;
    } finally {
      setIsSaving(false);
    }
  }

  async function runBulk(operation: 'archive' | 'delete' | 'tag') {
    if (operation === 'tag') {
      if (bulkSelection.size) setActionDialog({ kind: 'bulk-tag' });
      return;
    }
    const idsByEntity = [...bulkSelection].reduce<Record<string, string[]>>((accumulator, key) => {
      const [entity, id] = key.split(':');
      accumulator[entity] = [...(accumulator[entity] || []), id];
      return accumulator;
    }, {});
    setIsSaving(true);
    setError('');
    try {
      for (const [entityType, ids] of Object.entries(idsByEntity)) {
        await callBackend({ action: 'crm.bulk_update', entity_type: entityType, ids, operation });
      }
      setBulkSelection(new Set());
      await refresh();
    } catch (bulkError) {
      setError(bulkError instanceof Error ? bulkError.message : 'Bulk action failed.');
    } finally {
      setIsSaving(false);
    }
  }

  async function submitBulkTag(tag: string): Promise<boolean> {
    if (!tag.trim()) return false;
    const idsByEntity = [...bulkSelection].reduce<Record<string, string[]>>((accumulator, key) => {
      const [entity, id] = key.split(':');
      accumulator[entity] = [...(accumulator[entity] || []), id];
      return accumulator;
    }, {});
    setIsSaving(true);
    setError('');
    try {
      for (const [entityType, ids] of Object.entries(idsByEntity)) {
        await callBackend({ action: 'crm.bulk_update', entity_type: entityType, ids, operation: 'tag', tag: tag.trim() });
      }
      setBulkSelection(new Set());
      await refresh();
      return true;
    } catch (bulkError) {
      setError(bulkError instanceof Error ? bulkError.message : 'Bulk action failed.');
      return false;
    } finally {
      setIsSaving(false);
    }
  }

  async function deleteSelectedRecord() {
    if (!window.confirm('Delete this CRM record?')) return;
    await mutateSelectedRecord('crm.delete_record', {}, true);
  }

  async function archiveSelectedRecord() {
    await mutateSelectedRecord('crm.archive_record', {}, true);
  }

  return {
    archiveSelectedRecord,
    configureStage,
    convertSelectedLead,
    deleteSelectedRecord,
    deletePipelineStage,
    moveDeal,
    runBulk,
    submitBulkTag,
    submitPipelineStage,
    submitRecordTag,
    tagSelectedRecord
  };
}
