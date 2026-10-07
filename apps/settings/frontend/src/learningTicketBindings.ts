import type { LearningView } from './learningController';
import { ticketCommandForMove } from './learningTickets';

export function bindLearningTickets(state: LearningView, command: (id: string, action: string) => void, change: (changes: Partial<LearningView>) => void) {
  document.querySelectorAll<HTMLElement>('[data-ticket-filter]').forEach((button) => button.addEventListener('click', () => change({ ticketFilter: button.dataset.ticketFilter as LearningView['ticketFilter'] })));
  document.querySelectorAll<HTMLElement>('[data-ticket-view]').forEach((button) => button.addEventListener('click', () => change({ ticketView: button.dataset.ticketView as LearningView['ticketView'] })));
  document.querySelector<HTMLInputElement>('#ticket-search')?.addEventListener('input', (event) => change({ ticketSearch: (event.target as HTMLInputElement).value }));
  document.querySelector<HTMLSelectElement>('#ticket-category')?.addEventListener('change', (event) => change({ ticketCategory: (event.target as HTMLSelectElement).value }));
  let dragging = '';
  document.querySelectorAll<HTMLElement>('[data-learning-drag]').forEach((handle) => {
    handle.addEventListener('dragstart', (event) => {
      if (state.saving) { event.preventDefault(); return; }
      dragging = handle.dataset.learningDrag!;
      event.dataTransfer?.setData('text/plain', dragging);
      if (event.dataTransfer) event.dataTransfer.effectAllowed = 'move';
    });
    handle.addEventListener('dragend', () => { dragging = ''; document.querySelectorAll('.ticket-column.is-over').forEach((column) => column.classList.remove('is-over')); });
  });
  document.querySelectorAll<HTMLElement>('[data-ticket-column]').forEach((column) => {
    const action = () => { const item = state.data?.items.find((item) => item.id === dragging); return item && ticketCommandForMove(item, column.dataset.ticketColumn!); };
    column.addEventListener('dragover', (event) => { if (!state.saving && action()) { event.preventDefault(); column.classList.add('is-over'); } });
    column.addEventListener('dragleave', (event) => { if (!column.contains(event.relatedTarget as Node)) column.classList.remove('is-over'); });
    column.addEventListener('drop', (event) => { event.preventDefault(); const next = action(); column.classList.remove('is-over'); if (next && !state.saving) command(dragging, next); dragging = ''; });
  });
}
