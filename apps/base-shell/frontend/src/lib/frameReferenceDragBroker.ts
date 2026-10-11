import { isMaverickFrameInScope, postToMaverickFrame, registeredMaverickFrameElement, subscribeMaverickFrameRegistry, type MaverickFrameScope } from '../iframePolicy';

type DragMessage = {
  type: string;
  drag_id: string;
  x: number;
  y: number;
  viewport_width: number;
  viewport_height: number;
  label?: string;
  transfer?: { type: string; data: string };
};

/** Route a captured pointer drag without reading either isolated frame's DOM. */
export function installFrameReferenceDragBroker(scope: MaverickFrameScope): () => void {
  let active: { frame: HTMLIFrameElement; origin: string; message: DragMessage; preview: HTMLElement; overlay: HTMLElement } | null = null;
  function clear() {
    if (active) {
      active.preview.remove();
      active.overlay.remove();
      postToMaverickFrame(active.frame, { type: 'maverick.reference-drag.finished', drag_id: active.message.drag_id });
    }
    active = null;
  }
  function move(x: number, y: number) {
    if (!active) return;
    active.preview.style.left = `${x + 14}px`;
    active.preview.style.top = `${y + 14}px`;
  }
  function drop(x: number, y: number) {
    if (!active) return;
    const { transfer, drag_id } = active.message;
    clear();
    const target = document.elementFromPoint(x, y);
    if (!(target instanceof HTMLIFrameElement) || !isMaverickFrameInScope(target, scope)) return;
    const targetRect = target.getBoundingClientRect();
    postToMaverickFrame(target, {
      type: 'maverick.reference-drag.drop', drag_id, transfer,
      x: (x - targetRect.left) * target.offsetWidth / targetRect.width - target.clientLeft,
      y: (y - targetRect.top) * target.offsetHeight / targetRect.height - target.clientTop,
    });
  }
  function onMessage(event: MessageEvent) {
    const message = event.data as DragMessage | null;
    if (!message || !['maverick.reference-drag.start', 'maverick.reference-drag.move', 'maverick.reference-drag.end', 'maverick.reference-drag.cancel'].includes(message.type)) return;
    const frame = registeredMaverickFrameElement(event, scope);
    if (!frame || typeof message.drag_id !== 'string' || !message.drag_id || message.drag_id.length > 128) return;
    if (message.type === 'maverick.reference-drag.cancel') {
      if (active?.frame === frame && active.message.drag_id === message.drag_id) clear();
      return;
    }
    if (![message.x, message.y, message.viewport_width, message.viewport_height].every(Number.isFinite)
      || message.viewport_width <= 0 || message.viewport_height <= 0) return;
    if (message.type === 'maverick.reference-drag.start') {
      const transfer = message.transfer;
      if (!transfer || typeof transfer.type !== 'string' || !/^application\/x-maverick-[a-z-]+$/.test(transfer.type)
        || typeof transfer.data !== 'string' || transfer.data.length > 65_536
        || typeof message.label !== 'string' || message.label.length > 512) return;
      clear();
      const preview = document.createElement('div');
      preview.className = 'bs-reference-drag-preview';
      preview.setAttribute('aria-hidden', 'true');
      preview.textContent = message.label;
      const overlay = document.createElement('div');
      overlay.className = 'bs-reference-drag-overlay';
      overlay.setAttribute('aria-hidden', 'true');
      overlay.onpointermove = (event) => move(event.clientX, event.clientY);
      overlay.onpointerup = (event) => drop(event.clientX, event.clientY);
      overlay.onpointercancel = clear;
      document.body.append(overlay, preview);
      active = { frame, origin: event.origin, message, preview, overlay };
    }
    if (!active || active.frame !== frame || active.message.drag_id !== message.drag_id) return;
    const rect = frame.getBoundingClientRect();
    const scaleX = rect.width / frame.offsetWidth;
    const scaleY = rect.height / frame.offsetHeight;
    const x = rect.left + frame.clientLeft * scaleX + message.x * frame.clientWidth * scaleX / message.viewport_width;
    const y = rect.top + frame.clientTop * scaleY + message.y * frame.clientHeight * scaleY / message.viewport_height;
    if (!Number.isFinite(x) || !Number.isFinite(y)) { clear(); return; }
    move(x, y);
    if (message.type === 'maverick.reference-drag.end') drop(x, y);
  }
  const onVisibility = () => { if (document.hidden) clear(); };
  const onKey = (event: KeyboardEvent) => { if (active && event.key === 'Escape') { event.preventDefault(); clear(); } };
  const stopRegistry = subscribeMaverickFrameRegistry(() => {
    if (active && (!isMaverickFrameInScope(active.frame, scope) || active.frame.dataset.maverickFrameOrigin !== active.origin)) clear();
  });
  window.addEventListener('message', onMessage);
  window.addEventListener('keydown', onKey);
  document.addEventListener('visibilitychange', onVisibility);
  return () => {
    clear();
    stopRegistry();
    window.removeEventListener('message', onMessage);
    window.removeEventListener('keydown', onKey);
    document.removeEventListener('visibilitychange', onVisibility);
  };
}
