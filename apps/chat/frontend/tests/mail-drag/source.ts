import { startMailThreadPointerDrag } from '../../../../mail/frontend/src/lib/mailThreadPointerDrag';
import { mailThreadDragPayloadFromThread, writeMailThreadDragData } from '../../../../mail/frontend/src/lib/mailThreadDragDrop';

Object.defineProperty(window, '__LOOPINO_PLATFORM_ORIGIN__', { value: new URLSearchParams(location.search).get('shell_origin') });
const row = document.getElementById('row')!;
const mail = document.getElementById('mail')!;
const thread = {
  id: 'thread-fixture', connection_id: 'fixture', subject: 'Synthetic email', snippet: 'Synthetic content',
  participants: [{ email: 'sender@example.com' }], last_message_at: '2026-10-11T12:00:00Z',
  labels: ['inbox'], unread: true, starred: false,
};
let cleanup: (() => void) | null = null;
row.onpointerdown = (event) => {
  cleanup?.();
  cleanup = startMailThreadPointerDrag(event, row, thread, (id) => { row.dataset.dragging = id; });
};
row.ondragstart = (event) => {
  if (cleanup) event.preventDefault();
  else writeMailThreadDragData(event.dataTransfer!, mailThreadDragPayloadFromThread(thread));
};
mail.onclick = () => { document.getElementById('opened')!.textContent = '1'; };
