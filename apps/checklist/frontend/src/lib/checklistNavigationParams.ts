export function scalarString(value: unknown) {
  return typeof value === 'string' ? value.trim() : '';
}

export function checklistIdFromParams(params: Record<string, unknown>) {
  const directChecklistId = scalarString(params.checklist_id);
  if (directChecklistId) {
    return directChecklistId;
  }
  const appPage = scalarString(params.app_page);
  const match = appPage.match(/^checklists?\/([^/?#]+)$/);
  return match?.[1] || '';
}

export function isChecklistBoardParams(params: Record<string, unknown>) {
  if (checklistIdFromParams(params)) {
    return false;
  }
  const appPage = scalarString(params.app_page).replace(/^\/+|\/+$/g, '');
  return !appPage || appPage === 'agent-plans' || appPage === 'plans' || appPage === 'checklists';
}

export function shouldCreateNewChecklist(params: Record<string, unknown>) {
  return params.new_checklist === true || scalarString(params.new_checklist) === 'true';
}
