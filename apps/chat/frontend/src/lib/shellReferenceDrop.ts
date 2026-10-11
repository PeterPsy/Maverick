import { isExactMaverickParentMessage } from '@maverick/pwa-cache';
import { appReferenceMentionItemsFromDataTransfer, hasAppReferenceDragData } from './storageDragReferences';

/** Reuse the composer's validated drop path after the shell resolves the target frame. */
export function listenForShellReferenceDrops(): () => void {
  function onMessage(event: MessageEvent) {
    if (!isExactMaverickParentMessage(event) || event.data?.type !== 'maverick.reference-drag.drop') return;
    const { x, y, transfer } = event.data;
    if (!Number.isFinite(x) || !Number.isFinite(y) || !transfer || typeof transfer.type !== 'string'
      || typeof transfer.data !== 'string' || transfer.data.length > 65_536) return;
    const target = document.elementFromPoint(x, y);
    if (!target?.closest('.chatapp-root, .chat-floating-widget-shell, .chat-floating-widget-launcher')) return;
    const dataTransfer = new DataTransfer();
    dataTransfer.setData(transfer.type, transfer.data);
    dataTransfer.effectAllowed = 'copy';
    if (!hasAppReferenceDragData(dataTransfer) || !appReferenceMentionItemsFromDataTransfer(dataTransfer).length) return;
    target.dispatchEvent(new DragEvent('drop', { bubbles: true, cancelable: true, clientX: x, clientY: y, dataTransfer }));
  }
  window.addEventListener('message', onMessage);
  return () => window.removeEventListener('message', onMessage);
}
