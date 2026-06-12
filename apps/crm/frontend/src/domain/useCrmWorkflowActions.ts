import { callBackend, WorkflowProposalPreviewPayload } from '../api';
import { CrmActionContext } from './actionContext';

type WorkflowProposalAction = 'approve' | 'apply' | 'dismiss' | 'reject';

export function useCrmWorkflowActions({ refresh, setError, setIsSaving }: CrmActionContext) {
  async function reviewWorkflowProposal(id: string, action: WorkflowProposalAction) {
    setIsSaving(true);
    setError('');
    try {
      if (action === 'approve') {
        await callBackend({ action: 'crm.approve_workflow_proposal', id });
      } else if (action === 'apply') {
        await callBackend({ action: 'crm.apply_workflow_proposal', id });
      } else if (action === 'reject') {
        await callBackend({ action: 'crm.reject_workflow_proposal', id });
      } else {
        await callBackend({ action: 'crm.dismiss_workflow_proposal', id, status: 'dismissed' });
      }
      await refresh();
      return true;
    } catch (workflowError) {
      setError(workflowError instanceof Error ? workflowError.message : 'Unable to update workflow proposal.');
      return false;
    } finally {
      setIsSaving(false);
    }
  }

  async function previewWorkflowProposal(id: string) {
    setIsSaving(true);
    setError('');
    try {
      return await callBackend<WorkflowProposalPreviewPayload>({ action: 'crm.workflow_proposal_preview', id });
    } catch (workflowError) {
      setError(workflowError instanceof Error ? workflowError.message : 'Unable to preview workflow proposal.');
      throw workflowError;
    } finally {
      setIsSaving(false);
    }
  }

  return { reviewWorkflowProposal, previewWorkflowProposal };
}
