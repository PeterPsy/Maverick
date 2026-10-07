import type { LearningItem, LearningView } from './learningController';
import { escapeHtml as e } from './html';

export const ticketState = (item: LearningItem) => ['rejected', 'undone', 'undoing'].includes(item.status) ? item.status : item.implementation?.status || item.status;
const columns = [
  { id: 'proposed', label: 'Proposed', states: ['pending'], hint: 'Accept to start a Chat agent' },
  { id: 'queued', label: 'Queued', states: ['accepted', 'queued', 'launching'], hint: 'Starts when an agent slot is available' },
  { id: 'running', label: 'In progress', states: ['running', 'stopping'], hint: 'Follow the agent in Chat' },
  { id: 'review', label: 'To verify', states: ['awaiting_review'], hint: 'Check the result before completing' },
  { id: 'attention', label: 'Needs attention', states: ['failed', 'cancelled'], hint: 'Inspect the chat and retry when ready' },
  { id: 'done', label: 'Done', states: ['implemented'], hint: 'Implementation confirmed' },
  { id: 'closed', label: 'Dismissed', states: ['rejected'], hint: 'Proposals you chose to dismiss' },
];
const memoryColumns = [
  { id: 'proposed', label: 'Proposed', states: ['pending', 'checking'], hint: 'Accept to start a Memory agent' },
  { id: 'queued', label: 'Queued', states: ['accepted', 'queued', 'launching'], hint: 'One Memory chat at a time' },
  { id: 'running', label: 'In progress', states: ['running', 'saving', 'stopping', 'undoing'], hint: 'Verifies sources and saves the approved fact' },
  { id: 'attention', label: 'Needs attention', states: ['failed', 'cancelled'], hint: 'Read the chat before retrying' },
  { id: 'done', label: 'Saved', states: ['saved'], hint: 'Confirmed by the Memory provider' },
  { id: 'undone', label: 'Undone', states: ['undone'], hint: 'Saves you chose to undo' },
  { id: 'closed', label: 'Dismissed', states: ['rejected'], hint: 'Facts you chose to dismiss' },
];
const labels: Record<string, string> = { pending: 'Proposed', checking: 'Checking Memory', saving: 'Saving', saved: 'Saved', undoing: 'Undoing', undone: 'Undone', accepted: 'Accepted · not started', queued: 'Queued', launching: 'Starting chat', running: 'In progress', stopping: 'Stopping', awaiting_review: 'To verify', failed: 'Failed', cancelled: 'Stopped', implemented: 'Done', rejected: 'Dismissed' };
const closed = (item: LearningItem) => ['implemented', 'rejected', 'saved', 'undone'].includes(ticketState(item));

export function ticketCommands(item: LearningItem): [string, string][] {
  const state = ticketState(item);
  if (state === 'pending') return [[item.kind === 'memory' ? 'approve' : 'accept', item.kind === 'memory' ? 'Accept & save' : 'Accept & start'], ['reject', 'Dismiss']];
  if (state === 'saved') return item.details.node_created ? [['undo', 'Undo save']] : [];
  if (state === 'accepted') return [['start', 'Start implementation'], ['reject', 'Dismiss']];
  if (['queued', 'launching', 'running'].includes(state)) return [['stop', state === 'queued' ? 'Remove from queue' : 'Stop implementation']];
  if (state === 'awaiting_review') return [['implemented', 'Confirm implemented'], ['retry', 'Continue fixing']];
  if (['failed', 'cancelled'].includes(state)) return [['retry', 'Retry in same chat'], ['reject', 'Dismiss']];
  return [];
}

export function ticketCommandForMove(item: LearningItem, column: string): string | undefined {
  const state = ticketState(item);
  if (column === 'queued') return state === 'pending' ? item.kind === 'memory' ? 'approve' : 'accept' : state === 'accepted' ? 'start' : ['failed', 'cancelled', 'awaiting_review'].includes(state) ? 'retry' : undefined;
  if (column === 'done' && state === 'awaiting_review') return 'implemented';
  if (column === 'closed' && ['pending', 'accepted', 'failed', 'cancelled'].includes(state)) return 'reject';
  return undefined;
}

export function ticketCard(item: LearningItem, saving: boolean, compact = true): string {
  const state = ticketState(item);
  const commands = ticketCommands(item);
  const button = (command: string, label: string) => `<button class="settings-secondary ${command === 'accept' ? 'ticket-primary' : ''}" data-learning-item="${e(item.id)}" data-learning-command="${command}" ${saving ? 'disabled' : ''}>${label}</button>`;
  const sessions = [...new Set(item.evidence.map((source) => source.session_id))];
  const matches = item.details.memory_matches || [];
  const details = `${compact ? `<p>${e(item.body)}</p>` : ''}<dl class="learning-proposal-details">${(['expected_impact', 'verification'] as const).filter((key) => item.details[key]).map((key) => `<dt>${key === 'verification' ? 'Verification' : 'Expected impact'}</dt><dd>${e(item.details[key]!)}</dd>`).join('')}</dl>
    ${item.evidence.map((source) => `<blockquote><p>${e(source.quote)}</p><small>${e(source.role)} · ${e(source.turn_id)} · <a href="/app/chat/threads/${encodeURIComponent(source.session_id)}">Source chat</a></small></blockquote>`).join('')}
    ${item.implementation?.summary ? `<details data-learning-disclosure="${e(item.id)}-summary"><summary>Agent result</summary><p class="ticket-summary">${e(item.implementation.summary)}</p></details>` : ''}
    ${item.status === 'pending' ? `<details data-learning-disclosure="${e(item.id)}-edit"><summary>Edit proposal</summary><label>Title<input data-learning-title="${e(item.id)}" value="${e(item.title)}" maxlength="240"></label><label>Description<textarea data-learning-body="${e(item.id)}" rows="3" maxlength="4000">${e(item.body)}</textarea></label>${button('edit', 'Save edit')}</details>` : ''}`;
  return `<article class="learning-ticket ${compact ? '' : 'ticket-list-row'}" data-ticket-id="${e(item.id)}" data-ticket-state="${e(state)}">
    <div class="ticket-top"><span>${e(item.details.category || 'Improvement')}</span>${commands.length ? `<button class="ticket-grip" draggable="${!saving}" data-learning-drag="${e(item.id)}" aria-label="Move ${e(item.title)} between columns" title="Drag to Queued, Done or Dismissed; actions below also work with keyboard" ${saving ? 'disabled' : ''}><span class="material-symbols-rounded" aria-hidden="true">drag_indicator</span></button>` : ''}</div>
    <h4>${e(item.title)}</h4><p class="ticket-description">${e(item.body)}</p>
    <div class="ticket-meta"><span>${e(labels[state] || state)}</span>${item.details.effort ? `<span>${e(item.details.effort)} effort</span>` : ''}<span>${sessions.length} source chat${sessions.length === 1 ? '' : 's'}${item.occurrences > 1 ? ` · ${item.occurrences} observations` : ''}</span></div>
    ${item.implementation?.error ? `<p class="learning-error" role="status">${e(item.implementation.error)}</p>` : ''}
    ${state === 'awaiting_review' ? '<p class="ticket-note">The agent finished its turn. Review the changes and checks in Chat.</p>' : ''}
    ${state === 'pending' && item.kind === 'memory' && matches.length ? `<label>Memory destination<select data-learning-target="${e(item.id)}" aria-label="Memory destination"><option value="">Choose destination</option>${matches.map((match) => `<option value="${e(match.id)}">Attach to ${e(match.title)}</option>`).join('')}<option value="new">Create separate fact</option></select></label>` : ''}
    ${item.details.memory_check_error || item.details.save_error ? `<p class="learning-error">${e(item.details.save_error || item.details.memory_check_error!)}</p>` : ''}
    <div class="learning-actions">${item.kind === 'memory' && item.status === 'saved' ? `<a class="settings-secondary" href="/app/${encodeURIComponent(item.provider_id || 'memory')}/nodes/${encodeURIComponent(item.node_id)}">Open Memory</a>` : ''}${item.implementation?.session_id ? `<a class="settings-secondary" href="/app/chat/threads/${encodeURIComponent(item.implementation.session_id)}">Open work chat <span aria-hidden="true">↗</span></a>` : ''}${commands.slice(0, 1).map(([command, label]) => button(command, label)).join('')}</div>
    <details class="ticket-details" data-learning-disclosure="${e(item.id)}-ticket"><summary>Details &amp; evidence</summary>${details}${commands.slice(1).map(([command, label]) => button(command, label)).join('')}</details>
  </article>`;
}

export function learningTicketsHtml(state: LearningView): string {
  const memory = state.tab === 'memory';
  const kind = memory ? 'memory' : 'improvement';
  const all = state.data!.items.filter((item) => item.kind === kind);
  const filter = state.ticketFilter || 'open';
  const view = state.ticketView || 'board';
  const search = (state.ticketSearch || '').trim().toLocaleLowerCase();
  const categories = [...new Set(all.map((item) => item.details.category).filter(Boolean))].sort();
  const items = all.filter((item) => (filter === 'all' || (filter === 'closed' ? closed(item) : !closed(item)))
    && (!state.ticketCategory || item.details.category === state.ticketCategory)
    && (!search || `${item.title} ${item.body}`.toLocaleLowerCase().includes(search)));
  const visibleColumns = (memory ? memoryColumns : columns).filter((column) => filter === 'all' || (filter === 'closed' ? ['done', 'closed', 'undone'].includes(column.id) : !['done', 'closed', 'undone'].includes(column.id)));
  const project = state.data!.projects?.[kind];
  return `${state.error ? `<p class="learning-error" role="alert">${e(state.error)}</p>` : ''}${state.notice ? `<p class="ticket-queue-note" role="status" aria-live="polite">${e(state.notice)}</p>` : ''}<div class="ticket-toolbar"><div class="ticket-toolbar-title"><strong>${memory ? 'Memory' : 'Improvement'} tickets <span>${all.length}</span></strong><small>${memory ? 'Accept a fact to start a Chat agent that verifies its sources and saves it to Memory.' : 'Accept a proposal to start a Chat agent with its source context.'}${project ? ` <a href="/app/chat/projects/${encodeURIComponent(project)}">Open ${memory ? 'Memory' : 'Improvements'} project ↗</a>` : ''}</small></div>
    <div class="ticket-toolbar-controls"><div class="ticket-segment" role="group" aria-label="Ticket status filter">${(['open', 'all', 'closed'] as const).map((option) => `<button data-ticket-filter="${option}" aria-pressed="${filter === option}">${{open: 'Open', all: 'All', closed: 'Closed'}[option]}</button>`).join('')}</div>
    <div class="ticket-segment" role="group" aria-label="Ticket view">${(['board', 'list'] as const).map((option) => `<button data-ticket-view="${option}" aria-pressed="${view === option}" aria-label="${option === 'board' ? 'Kanban board' : 'Ticket list'}"><span class="material-symbols-rounded" aria-hidden="true">${option === 'board' ? 'view_kanban' : 'view_list'}</span></button>`).join('')}</div></div>
    <input id="ticket-search" type="search" aria-label="Search improvement tickets" placeholder="Search tickets…" value="${e(state.ticketSearch || '')}"><select id="ticket-category" aria-label="Ticket category"><option value="">All categories</option>${categories.map((category) => `<option value="${e(category!)}" ${category === state.ticketCategory ? 'selected' : ''}>${e(category!)}</option>`).join('')}</select></div>
    <p class="ticket-queue-note">${memory ? 'One Memory work chat runs at a time. Saved means the provider confirmed the write.' : `Up to ${state.data!.settings.improvement_concurrency ?? 4} improvement chats run in parallel. Configure the limit in Usage & retention.`} Accepted tickets use normal Chat usage; analysis pause and allowance apply to analysis.${state.data!.items.length >= 200 ? ' Showing the first 200 learning results.' : ''}</p>
    ${state.data!.runtime_ready === false ? '<p class="learning-notice" role="status">Work chats are waiting for the backend update. Accepted tickets stay queued until launching is available.</p>' : ''}
    ${view === 'board' ? `<div class="learning-kanban" role="region" aria-label="Improvement ticket board" tabindex="0">${visibleColumns.map((column) => { const cards = items.filter((item) => column.states.includes(ticketState(item))); return `<section class="ticket-column" data-ticket-column="${column.id}" aria-label="${column.label}"><header><h4><i aria-hidden="true"></i>${column.label}<span>${cards.length}</span></h4><small>${column.hint}</small></header><div class="ticket-dropzone">${cards.map((item) => ticketCard(item, state.saving)).join('') || '<div class="ticket-column-empty">No tickets</div>'}</div></section>`; }).join('')}</div>` : `<div class="learning-list">${items.map((item) => ticketCard(item, state.saving, false)).join('') || '<div class="learning-empty"><strong>No matching tickets</strong><p>Change the filters or wait for new proposals.</p></div>'}</div>`}`;
}
