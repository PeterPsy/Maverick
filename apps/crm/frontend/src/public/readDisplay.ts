import { callBackend } from '../api';

/** Public reads use native CRM actions, not the private platform cache protocol. */
export function readPublicDisplay<T>(parameters: Record<string, unknown>, signal?: AbortSignal): Promise<T> {
  const { kind, ...body } = parameters;
  const actions: Record<string, string> = { bootstrap: 'bootstrap', schema: 'schema', records_table: 'records_table', pipeline_board: 'pipeline_board', get: 'get_record', search: 'search' };
  if (typeof kind !== 'string' || !actions[kind]) throw new Error('Unsupported public CRM read.');
  return callBackend<T>({ ...body, action: 'crm.' + actions[kind], ...(kind === 'records_table' ? {
    sort: { field: body.sort_field || 'updated_at', direction: body.sort_direction || 'desc' },
    pagination: { cursor: body.cursor || '', limit: body.limit || 50 },
  } : {}) }, signal);
}
