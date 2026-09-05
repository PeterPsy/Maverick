import { displayRecord, projectDisplayModel, type DisplayModelSchema } from '@maverick/pwa-cache';
const text = (fields: string[]) => Object.fromEntries(fields.map((field) => [field, 'string']));
const schemas: Record<string, DisplayModelSchema> = {
  projects: { required: ['projects', 'has_more'], fields: { has_more: 'boolean' }, lists: { projects: {
    required: ['project_id', 'name'], fields: text(['project_id', 'name', 'created_at', 'updated_at']),
  } } },
  threads: { required: ['threads'], lists: { threads: {
    required: ['thread_id', 'runtime_session_id', 'title'],
    fields: { ...text(['thread_id', 'runtime_session_id', 'title', 'project_id', 'agent_label', 'source_app_id', 'created_at', 'updated_at', 'last_user_message_at', 'last_completed_response_at']), archived: 'boolean' },
  } }, objects: { page: { fields: { cursor: 'string', has_more: 'boolean', limit: 'number', total: 'number', filtered_total: 'number' } } } },
  messages: { required: ['messages'], lists: { messages: { required: ['id', 'turn_id', 'role', 'text', 'created_at'], fields: text(['id', 'turn_id', 'role', 'text', 'created_at']) } } },
};
export type ChatReadModel = { kind: string; data: Record<string, unknown> };
export function sanitizeChatReadModel(value: unknown): ChatReadModel | null {
  const raw = displayRecord(value);
  if (!raw || typeof raw.kind !== 'string' || !Object.hasOwn(schemas, raw.kind)) return null;
  const data = projectDisplayModel(raw.data, schemas[raw.kind]);
  if (!data) return null;
  if (raw.kind === 'messages' && (data.messages as Record<string, unknown>[]).some((message) => !['user', 'assistant'].includes(String(message.role)) || !Number.isFinite(Date.parse(String(message.created_at))))) return null;
  return { kind: raw.kind, data };
}
