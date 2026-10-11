import type { MailThread } from '../api';
import { MAIL_THREAD_DRAG_DATA_TYPE, mailThreadDragPayloadFromThread } from './mailThreadDragDrop';

function mailPointerDragHostOrigin(): string | null {
  const origin = (window as Window & { __MAVERICK_PLATFORM_ORIGIN__?: unknown }).__MAVERICK_PLATFORM_ORIGIN__;
  if (window.parent === window || typeof origin !== 'string') return null;
  try {
    return /^https?:\/\//u.test(origin) && new URL(origin).origin === origin ? origin : null;
  } catch { return null; }
}

/** Pointer capture keeps coordinates and cancellation reliable across isolated origins. */
export function startMailThreadPointerDrag(
  down: Pick<PointerEvent, 'button' | 'pointerType' | 'pointerId' | 'clientX' | 'clientY'>,
  row: HTMLElement,
  thread: MailThread,
  onDraggingChange: (id: string) => void,
): (() => void) | null {
  const origin = mailPointerDragHostOrigin();
  if (!origin || down.button !== 0 || down.pointerType === 'touch') return null;
  const dragId = crypto.randomUUID();
  let dragging = false;
  let finished = false;
  let suppressClick = false;
  let clickTimer: ReturnType<typeof setTimeout> | undefined;
  const post = (type: string, point?: { clientX: number; clientY: number }) => window.parent.postMessage({
    type: `maverick.reference-drag.${type}`, drag_id: dragId,
    ...(point ? { x: point.clientX, y: point.clientY, viewport_width: window.innerWidth, viewport_height: window.innerHeight } : {}),
    ...(type === 'start' ? {
      label: (thread.subject.trim() || 'Email thread').slice(0, 512),
      transfer: { type: MAIL_THREAD_DRAG_DATA_TYPE, data: JSON.stringify(mailThreadDragPayloadFromThread(thread)) },
    } : {}),
  }, origin);
  function stopClick(event: MouseEvent) {
    if (!suppressClick || !(event.target instanceof Node) || !row.contains(event.target)) return;
    event.preventDefault();
    event.stopImmediatePropagation();
  }
  function finish(cancelled = true, point?: PointerEvent) {
    if (finished) return;
    finished = true;
    if (dragging) post(cancelled ? 'cancel' : 'end', point);
    window.removeEventListener('pointermove', move);
    window.removeEventListener('pointerup', up);
    window.removeEventListener('pointercancel', cancel);
    window.removeEventListener('keydown', key);
    window.removeEventListener('blur', cancel);
    window.removeEventListener('message', onHostMessage);
    row.removeEventListener('lostpointercapture', cancel);
    if (row.hasPointerCapture(down.pointerId)) row.releasePointerCapture(down.pointerId);
    onDraggingChange('');
    // A captured pointerup can also click the source row. It must not open the email.
    clickTimer = setTimeout(() => document.removeEventListener('click', stopClick, true), cancelled ? 500 : 0);
  }
  function move(event: PointerEvent) {
    if (event.pointerId !== down.pointerId) return;
    if (!dragging) {
      if (Math.hypot(event.clientX - down.clientX, event.clientY - down.clientY) < 6) return;
      dragging = true;
      suppressClick = true;
      row.setPointerCapture(down.pointerId);
      onDraggingChange(thread.id);
      post('start', event);
    } else post('move', event);
    event.preventDefault();
  }
  function up(event: PointerEvent) { if (event.pointerId === down.pointerId) finish(false, event); }
  function cancel(event?: Event) {
    if (event instanceof PointerEvent && event.pointerId !== down.pointerId) return;
    finish();
  }
  function key(event: KeyboardEvent) { if (event.key === 'Escape') { event.preventDefault(); finish(); } }
  function onHostMessage(event: MessageEvent) {
    if (event.source === window.parent && event.origin === origin
      && event.data?.type === 'maverick.reference-drag.finished' && event.data.drag_id === dragId) finish();
  }
  window.addEventListener('pointermove', move);
  window.addEventListener('pointerup', up);
  window.addEventListener('pointercancel', cancel);
  window.addEventListener('keydown', key);
  window.addEventListener('blur', cancel);
  window.addEventListener('message', onHostMessage);
  row.addEventListener('lostpointercapture', cancel);
  document.addEventListener('click', stopClick, true);
  return () => {
    finish();
    clearTimeout(clickTimer);
    document.removeEventListener('click', stopClick, true);
  };
}
