import { escapeHtml as e } from './html';

export const statusLabel = (status: string) => ({ pending: 'To review', checking: 'Checking Memory', saving: 'Saving', saved: 'Saved', undoing: 'Undoing', undone: 'Undone', rejected: 'Rejected', accepted: 'Accepted', implemented: 'Implemented', queued: 'Waiting', running: 'Analyzing', completed: 'Completed', failed: 'Failed', cancelled: 'Cancelled' }[status] || status);

export function date(timestamp: number) { return e(new Date(timestamp * 1000).toLocaleString()); }
