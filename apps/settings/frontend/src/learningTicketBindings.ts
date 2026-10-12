import { bindControl } from './controlBindings';
import type { LearningView } from './learningController';
import { ticketCommandForMove } from './learningTickets';

export function bindLearningTickets(state: LearningView, command: (id: string, action: string) => void, change: (changes: Partial<LearningView>) => void) {
  document.querySelectorAll<HTMLElement>('[data-ticket-filter]').forEach((button) => bindControl(button, 'click', () => change({ ticketFilter: button.dataset.ticketFilter as LearningView['ticketFilter'] })));
  document.querySelectorAll<HTMLElement>('[data-ticket-view]').forEach((button) => bindControl(button, 'click', () => change({ ticketView: button.dataset.ticketView as LearningView['ticketView'] })));
  bindControl(document.querySelector<HTMLInputElement>('#ticket-search'), 'input', (event) => change({ ticketSearch: (event.target as HTMLInputElement).value }));
  bindControl(document.querySelector<HTMLSelectElement>('#ticket-category'), 'change', (event) => change({ ticketCategory: (event.target as HTMLSelectElement).value }));
  let dragging = '';
  document.querySelectorAll<HTMLElement>('[data-learning-drag]').forEach((handle) => {
    bindControl(handle, 'dragstart', (event) => {
      if (state.saving) { event.preventDefault(); return; }
      dragging = handle.dataset.learningDrag!;
      event.dataTransfer?.setData('text/plain', dragging);
      if (event.dataTransfer) event.dataTransfer.effectAllowed = 'move';
    });
    bindControl(handle, 'dragend', () => { dragging = ''; document.querySelectorAll('.ticket-column.is-over').forEach((column) => column.classList.remove('is-over')); });
  });
  document.querySelectorAll<HTMLElement>('[data-ticket-column]').forEach((column) => {
    const action = () => { const item = state.data?.items.find((item) => item.id === dragging); return item && ticketCommandForMove(item, column.dataset.ticketColumn!); };
    bindControl(column, 'dragover', (event) => { if (!state.saving && action()) { event.preventDefault(); column.classList.add('is-over'); } });
    bindControl(column, 'dragleave', (event) => { if (!column.contains(event.relatedTarget as Node)) column.classList.remove('is-over'); });
    bindControl(column, 'drop', (event) => { event.preventDefault(); const next = action(); column.classList.remove('is-over'); if (next && !state.saving) command(dragging, next); dragging = ''; });
  });
}
