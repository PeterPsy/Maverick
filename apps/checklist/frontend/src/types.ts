export type ChecklistMode = 'simple' | 'agent_plan' | 'execution';

export type ChecklistStatus = 'active' | 'in-progress' | 'blocked' | 'completed' | 'failed';

export type TaskStatus = 'pending' | 'in-progress' | 'need-help' | 'blocked' | 'completed' | 'failed';

export type Priority = 'low' | 'medium' | 'high' | 'critical';

export interface AgentDialogRef {
  id: string;
  title: string;
  summary: string;
  ref: string;
  agent_ref: string;
}

export interface AgentSubtask {
  id: string;
  title: string;
  description: string;
  status: TaskStatus;
  priority: Priority;
  checked: boolean;
  tools: string[];
  blocked_reason: string;
  agent_ref: string;
  source_ref: string;
  agent_dialogs: AgentDialogRef[];
}

export interface AgentTask {
  id: string;
  title: string;
  description: string;
  status: TaskStatus;
  priority: Priority;
  checked: boolean;
  level: number;
  dependencies: string[];
  tools: string[];
  subtasks: AgentSubtask[];
  blocked_reason: string;
  agent_ref: string;
  source_ref: string;
  agent_dialogs: AgentDialogRef[];
}

export interface ChecklistSection {
  id: string;
  title: string;
  tasks: AgentTask[];
}

export interface ChecklistItem {
  id: string;
  workspace_id: string;
  profile: string | null;
  mode: ChecklistMode;
  kind: string;
  title: string;
  summary: string;
  sections: ChecklistSection[];
  source_type: string;
  source_ref: string;
  status: ChecklistStatus;
  priority: Priority;
  created_at: string;
  updated_at: string;
  task_count: number;
  checked_count: number;
  blocked_count: number;
  failed_count: number;
}

export interface ChecklistActionResult {
  action?: string;
  checklist?: ChecklistItem;
  items?: ChecklistItem[];
  task?: AgentTask;
  subtask?: AgentSubtask;
  view_state?: ChecklistViewState;
  error?: string;
  detail?: string;
}

export interface ChecklistViewState {
  mode?: string;
  query?: string;
  title?: string;
  refs?: Array<Record<string, string>>;
}

export interface WidgetContext {
  content?: {
    kind?: string;
    payload?: Record<string, unknown>;
    memory?: Record<string, unknown>;
  };
}
