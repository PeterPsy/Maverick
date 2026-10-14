import { isLoopinoFrameInScope, postToLoopinoFrame, registeredLoopinoFrameElement, subscribeLoopinoFrameRegistry, type LoopinoFrameScope } from '../iframePolicy';

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
export function installFrameReferenceDragBroker(scope: LoopinoFrameScope): () => void {
  let active: { frame: HTMLIFrameElement; origin: string; message: DragMessage; preview: HTMLElement; overlay: HTMLElement; hoverFrame: HTMLIFrameElement | null } | null = null;
  function postTarget(frame: HTMLIFrameElement, type: 'over' | 'leave', x: number, y: number) {
    if (!active || !isLoopinoFrameInScope(frame, scope)) return;
    const rect = frame.getBoundingClientRect();
    if (!rect.width || !rect.height) return;
    postToLoopinoFrame(frame, {
      type: `loopino.reference-drag.${type}`, drag_id: active.message.drag_id, transfer: active.message.transfer,
      x: (x - rect.left) * frame.offsetWidth / rect.width - frame.clientLeft,
      y: (y - rect.top) * frame.offsetHeight / rect.height - frame.clientTop,
    });
  }
  function clear() {
    if (active) {
      if (active.hoverFrame) postTarget(active.hoverFrame, 'leave', 0, 0);
      active.preview.remove();
      active.overlay.remove();
      postToLoopinoFrame(active.frame, { type: 'loopino.reference-drag.finished', drag_id: active.message.drag_id });
    }
    active = null;
  }
  function move(x: number, y: number) {
    if (!active) return;
    active.preview.style.left = `${x + 14}px`;
    active.preview.style.top = `${y + 14}px`;
    active.overlay.style.pointerEvents = 'none';
    const hit = document.elementFromPoint(x, y);
    active.overlay.style.pointerEvents = '';
    const target = hit instanceof HTMLIFrameElement && isLoopinoFrameInScope(hit, scope) ? hit : null;
    if (active.hoverFrame !== target && active.hoverFrame) postTarget(active.hoverFrame, 'leave', x, y);
    active.hoverFrame = target;
    if (target) postTarget(target, 'over', x, y);
  }
  function drop(x: number, y: number) {
    if (!active) return;
    const { transfer, drag_id } = active.message;
    clear();
    const target = document.elementFromPoint(x, y);
    if (!(target instanceof HTMLIFrameElement) || !isLoopinoFrameInScope(target, scope)) return;
    const targetRect = target.getBoundingClientRect();
    postToLoopinoFrame(target, {
      type: 'loopino.reference-drag.drop', drag_id, transfer,
      x: (x - targetRect.left) * target.offsetWidth / targetRect.width - target.clientLeft,
      y: (y - targetRect.top) * target.offsetHeight / targetRect.height - target.clientTop,
    });
  }
  function onMessage(event: MessageEvent) {
    const message = event.data as DragMessage | null;
    if (!message || !['loopino.reference-drag.start', 'loopino.reference-drag.move', 'loopino.reference-drag.end', 'loopino.reference-drag.cancel'].includes(message.type)) return;
    const frame = registeredLoopinoFrameElement(event, scope);
    if (!frame || typeof message.drag_id !== 'string' || !message.drag_id || message.drag_id.length > 128) return;
    if (message.type === 'loopino.reference-drag.cancel') {
      if (active?.frame === frame && active.message.drag_id === message.drag_id) clear();
      return;
    }
    if (![message.x, message.y, message.viewport_width, message.viewport_height].every(Number.isFinite)
      || message.viewport_width <= 0 || message.viewport_height <= 0) return;
    if (message.type === 'loopino.reference-drag.start') {
      const transfer = message.transfer;
      if (!transfer || typeof transfer.type !== 'string' || !/^application\/x-loopino-[a-z-]+$/.test(transfer.type)
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
      active = { frame, origin: event.origin, message, preview, overlay, hoverFrame: null };
    }
    if (!active || active.frame !== frame || active.message.drag_id !== message.drag_id) return;
    const rect = frame.getBoundingClientRect();
    const scaleX = rect.width / frame.offsetWidth;
    const scaleY = rect.height / frame.offsetHeight;
    const x = rect.left + frame.clientLeft * scaleX + message.x * frame.clientWidth * scaleX / message.viewport_width;
    const y = rect.top + frame.clientTop * scaleY + message.y * frame.clientHeight * scaleY / message.viewport_height;
    if (!Number.isFinite(x) || !Number.isFinite(y)) { clear(); return; }
    move(x, y);
    if (message.type === 'loopino.reference-drag.end') drop(x, y);
  }
  const onVisibility = () => { if (document.hidden) clear(); };
  const onKey = (event: KeyboardEvent) => { if (active && event.key === 'Escape') { event.preventDefault(); clear(); } };
  const stopRegistry = subscribeLoopinoFrameRegistry(() => {
    if (active && (!isLoopinoFrameInScope(active.frame, scope) || active.frame.dataset.loopinoFrameOrigin !== active.origin)) clear();
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
