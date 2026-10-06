import type { LearningItem } from './learningController';
import { escapeHtml as e } from './html';

export const statusLabel = (status: string) => ({ pending: 'To review', checking: 'Checking Memory', saving: 'Saving', saved: 'Saved', undoing: 'Undoing', undone: 'Undone', rejected: 'Rejected', accepted: 'Accepted', implemented: 'Implemented', queued: 'Waiting', running: 'Analyzing', completed: 'Completed', failed: 'Failed', cancelled: 'Cancelled' }[status] || status);

export function itemList(items: LearningItem[], saving: boolean) {
  if (!items.length) return '<div class="learning-empty"><strong>No results to review</strong><p>New suggestions will appear here after a captured conversation is analyzed.</p></div>';
  return `<div class="learning-list">${items.map((item) => {
    const busy = saving || ['checking', 'saving', 'undoing'].includes(item.status);
    const button = (command: string, label: string) => `<button class="settings-secondary" data-learning-item="${e(item.id)}" data-learning-command="${command}" ${busy ? 'disabled' : ''}>${label}</button>`;
    const matches = item.details.memory_matches || [];
    return `<article class="learning-row learning-item"><div class="learning-item-heading"><strong>${e(item.title)}</strong><span class="settings-pill">${e(statusLabel(item.status))}${item.occurrences > 1 ? ` · ${item.occurrences} observations` : ''}</span></div><p>${e(item.body)}</p>
    ${item.kind === 'improvement' ? `<dl class="learning-proposal-details">${(['category','expected_impact','effort','verification'] as const).filter((key) => item.details[key]).map((key) => `<dt>${{category:'Category',expected_impact:'Expected impact',effort:'Effort',verification:'Verification'}[key]}</dt><dd>${e(item.details[key] || '')}</dd>`).join('')}</dl>` : ''}
    ${item.details.memory_check_error || item.details.save_error ? `<p class="learning-error">${e(item.details.save_error || item.details.memory_check_error || '')}</p>` : ''}
    <details data-learning-disclosure="${e(item.id)}-evidence"><summary>Evidence${matches.length ? ' and Memory matches' : ''}</summary>${item.evidence.map((x) => `<blockquote><p>${e(x.quote)}</p><small>${e(x.role)} · ${e(x.turn_id)} · <a href="/app/chat/threads/${encodeURIComponent(x.session_id)}">Open chat</a>${typeof x.metrics.duration_seconds === 'number' ? ` · ${x.metrics.duration_seconds.toFixed(1)} s` : ''}</small></blockquote>`).join('')}${matches.length ? `<p>Related Memory: ${matches.map((x) => e(x.title)).join(', ')}. Choose a matching node to attach evidence, or explicitly create a separate fact.</p>` : ''}</details>
    ${item.status === 'pending' ? `<details data-learning-disclosure="${e(item.id)}-edit"><summary>Edit candidate</summary><label>Title<input data-learning-title="${e(item.id)}" value="${e(item.title)}" maxlength="240"></label><label>Description<textarea data-learning-body="${e(item.id)}" rows="3" maxlength="4000">${e(item.body)}</textarea></label>${button('edit', 'Save edit')}</details>` : ''}
    <div class="learning-actions">${item.status === 'pending' ? (item.kind === 'memory' ? `${matches.length ? `<select data-learning-target="${e(item.id)}" aria-label="Memory destination"><option value="">Choose destination</option>${matches.map((x) => `<option value="${e(x.id)}">Attach to ${e(x.title)}</option>`).join('')}<option value="new">Create separate fact</option></select>` : ''}${button('approve', 'Save to Memory')}` : button('accept', 'Accept proposal')) + button('reject', 'Reject') : ''}${item.status === 'accepted' ? button('implemented', 'Mark implemented') + button('reject', 'Reject') : ''}${item.status === 'saved' ? `<a class="settings-secondary" href="/app/${encodeURIComponent(item.provider_id || 'memory')}/nodes/${encodeURIComponent(item.node_id)}">Open Memory</a>${item.details.node_created ? button('undo', 'Undo save') : ''}` : ''}</div></article>`;
  }).join('')}</div>`;
}

export function date(timestamp: number) { return e(new Date(timestamp * 1000).toLocaleString()); }
