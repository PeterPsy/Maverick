import type { ChecklistActionResult, ChecklistItem, ChecklistMode, ChecklistViewState, TaskStatus, WidgetContext } from './types';

async function request(body: Record<string, unknown>): Promise<ChecklistActionResult> {
  const response = await fetch('/api/apps/checklist/backend', {
    method: 'POST',
    credentials: 'same-origin',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body)
  });
  const data = (await response.json()) as ChecklistActionResult;
  if (!response.ok || data.error) {
    throw new Error(data.detail || data.error || 'Checklist request failed.');
  }
  return data;
}

export async function listChecklists(options: { ignoreViewState?: boolean } = {}): Promise<ChecklistItem[]> {
  const data = await request({ action: 'list', ignore_view_state: options.ignoreViewState || undefined, limit: 500 });
  return data.items || [];
}

export async function readChecklist(id: string): Promise<ChecklistItem> {
  const data = await request({ action: 'read', id });
  if (!data.checklist) {
    throw new Error('Checklist not found.');
  }
  return data.checklist;
}

export async function createChecklist(mode: ChecklistMode = 'agent_plan'): Promise<ChecklistItem> {
  const data = await request({
    action: 'create',
    payload: {
      mode,
      title: mode === 'agent_plan' ? 'Agent plan' : 'Checklist',
      priority: 'medium',
      sections: [
        {
          id: 'section-default',
          title: mode === 'agent_plan' ? 'Plan' : '',
          tasks: [
            {
              id: `task-${Date.now().toString(16)}`,
              title: '',
              description: '',
              status: 'pending',
              priority: 'medium',
              dependencies: [],
              tools: [],
              subtasks: []
            }
          ]
        }
      ]
    }
  });
  if (!data.checklist) {
    throw new Error('Checklist was not created.');
  }
  return data.checklist;
}

export async function updateChecklist(id: string, checklist: ChecklistItem): Promise<ChecklistItem> {
  const data = await request({
    action: 'update',
    id,
    payload: {
      title: checklist.title,
      summary: checklist.summary,
      mode: checklist.mode,
      status: checklist.status,
      priority: checklist.priority,
      sections: checklist.sections
    }
  });
  if (!data.checklist) {
    throw new Error('Checklist was not saved.');
  }
  return data.checklist;
}

export async function deleteChecklist(id: string): Promise<void> {
  await request({ action: 'delete', id });
}

export async function readViewFilter(): Promise<ChecklistViewState> {
  const data = await request({ action: 'view_filter' });
  return data.view_state || {};
}

export async function setViewFilter(query: string): Promise<ChecklistViewState> {
  const data = await request({ action: 'set_view_filter', query });
  return data.view_state || {};
}

export async function setTaskStatus(
  checklistId: string,
  sectionId: string,
  taskId: string,
  status: TaskStatus
): Promise<void> {
  await request({ action: 'set_task_status', id: checklistId, section_id: sectionId, task_id: taskId, status });
}

export async function setSubtaskStatus(
  checklistId: string,
  sectionId: string,
  taskId: string,
  subtaskId: string,
  status: TaskStatus
): Promise<void> {
  await request({
    action: 'set_subtask_status',
    id: checklistId,
    section_id: sectionId,
    task_id: taskId,
    subtask_id: subtaskId,
    status
  });
}

export async function loadWidgetContext(token: string): Promise<WidgetContext> {
  const response = await fetch(`/api/apps/widgets/context/${encodeURIComponent(token)}`, {
    credentials: 'same-origin',
    headers: { Accept: 'application/json' }
  });
  if (!response.ok) {
    throw new Error('Unable to load widget context.');
  }
  const data = (await response.json()) as { context?: WidgetContext };
  return data.context || {};
}
