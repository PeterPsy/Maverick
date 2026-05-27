import { CrmActionContext } from './actionContext';
import { useCrmComposerActions } from './useCrmComposerActions';
import { useCrmImportAction } from './useCrmImportAction';
import { useCrmRecordActions } from './useCrmRecordActions';
import { useCrmViewActions } from './useCrmViewActions';
import { useCrmWorkflowActions } from './useCrmWorkflowActions';

export function useCrmActions(context: CrmActionContext) {
  return {
    ...useCrmComposerActions(context),
    ...useCrmImportAction(context),
    ...useCrmRecordActions(context),
    ...useCrmViewActions(context),
    ...useCrmWorkflowActions(context)
  };
}
