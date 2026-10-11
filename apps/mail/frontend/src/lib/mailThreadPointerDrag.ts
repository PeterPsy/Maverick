import { startMaverickReferencePointerDrag } from '@maverick/pwa-cache';
import type { MailThread } from '../api';
import { MAIL_THREAD_DRAG_DATA_TYPE, mailThreadDragPayloadFromThread } from './mailThreadDragDrop';

export function startMailThreadPointerDrag(
  down: Pick<PointerEvent, 'button' | 'pointerType' | 'pointerId' | 'clientX' | 'clientY'>,
  row: HTMLElement,
  thread: MailThread,
  onDraggingChange: (id: string) => void,
): (() => void) | null {
  return startMaverickReferencePointerDrag(down, row, () => ({
    label: thread.subject.trim() || 'Email thread',
    transfer: { type: MAIL_THREAD_DRAG_DATA_TYPE, data: JSON.stringify(mailThreadDragPayloadFromThread(thread)) },
  }), (dragging) => onDraggingChange(dragging ? thread.id : ''));
}
