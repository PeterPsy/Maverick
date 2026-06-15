import type { ChecklistItem } from '../types';

export const CHECKLIST_DRAG_DATA_TYPE = 'application/x-maverick-checklist';

export type ChecklistDragPayload = {
  checked_count: number;
  checklist_id: string;
  deep_link: string;
  mode: string;
  owner_app_id: string;
  status: string;
  summary: string;
  task_count: number;
  title: string;
};

type ChecklistDragDataTransfer = Pick<DataTransfer, 'setData'> & {
  effectAllowed?: DataTransfer['effectAllowed'];
};

export function checklistDragPayloadFromItem(
  item: ChecklistItem,
  ownerAppId = 'checklist'
): ChecklistDragPayload {
  const title = item.title.trim() || 'Checklist';
  const fallbackSummary = `${item.checked_count}/${item.task_count} checked`;
  return {
    checked_count: item.checked_count,
    checklist_id: item.id,
    deep_link: `/app/${encodeURIComponent(ownerAppId)}/checklists/${encodeURIComponent(item.id)}`,
    mode: item.mode,
    owner_app_id: ownerAppId,
    status: item.status,
    summary: item.summary.trim() || fallbackSummary,
    task_count: item.task_count,
    title,
  };
}

export function writeChecklistDragData(dataTransfer: ChecklistDragDataTransfer, payload: ChecklistDragPayload) {
  dataTransfer.setData(CHECKLIST_DRAG_DATA_TYPE, JSON.stringify(payload));
  dataTransfer.effectAllowed = 'copy';
}
