import { isExactLoopinoParentMessage, startLoopinoReferencePointerDrag } from '@loopino/pwa-cache';
import {
  STORAGE_FILE_DRAG_DATA_TYPE, STORAGE_FOLDER_DRAG_DATA_TYPE, STORAGE_SELECTION_DRAG_DATA_TYPE,
  STORAGE_DRIVE_FILE_DRAG_DATA_TYPE, STORAGE_DRIVE_FOLDER_DRAG_DATA_TYPE,
  readStorageFileDragData, readStorageFolderDragData, readStorageSelectionDragData,
  readStorageDriveFileDragData, readStorageDriveFolderDragData,
  writeStorageFileDragData, writeStorageFolderDragData, writeStorageSelectionDragData,
  writeStorageDriveFileDragData, writeStorageDriveFolderDragData,
} from './storageDragDrop';

const PAYLOAD_TYPES = [STORAGE_SELECTION_DRAG_DATA_TYPE, STORAGE_FILE_DRAG_DATA_TYPE, STORAGE_FOLDER_DRAG_DATA_TYPE,
  STORAGE_DRIVE_FILE_DRAG_DATA_TYPE, STORAGE_DRIVE_FOLDER_DRAG_DATA_TYPE];
const SOURCE_SELECTOR = '.animated-file-item[draggable="true"], .folder-card[draggable="true"], .storage-sidebar-widget [draggable="true"]';
const OPEN_BUTTON_SELECTOR = '.animated-file-preview-button, .animated-file-copy, .folder-card-open';

/** Rehydrate role markers through the same parsers/writers used by native Storage moves. */
export function storagePointerDropData(transfer: { type: string; data: string }, ownerAppId: string): DataTransfer | null {
  if (!PAYLOAD_TYPES.includes(transfer.type) || transfer.data.length > 65_536) return null;
  const data = new DataTransfer();
  data.setData(transfer.type, transfer.data);
  const file = readStorageFileDragData(data, ownerAppId);
  const folder = readStorageFolderDragData(data, ownerAppId);
  const selection = readStorageSelectionDragData(data, ownerAppId);
  const driveFile = readStorageDriveFileDragData(data, ownerAppId);
  const driveFolder = readStorageDriveFolderDragData(data, ownerAppId);
  if (file) writeStorageFileDragData(data, file);
  else if (folder) writeStorageFolderDragData(data, folder);
  else if (selection) writeStorageSelectionDragData(data, selection);
  else if (driveFile) writeStorageDriveFileDragData(data, driveFile);
  else if (driveFolder) writeStorageDriveFolderDragData(data, driveFolder);
  else return null;
  return data;
}

/** Adapt the app's existing drag handlers, including selections and Drive identities. */
export function installStoragePointerDrags(ownerAppId: string): () => void {
  let cleanup: (() => void) | null = null;
  let buildingPayload = false;
  let hoverTarget: Element | null = null;
  let hoverData: DataTransfer | null = null;
  function leave() {
    if (hoverTarget && hoverData) hoverTarget.dispatchEvent(new DragEvent('dragleave', { bubbles: true, cancelable: true, dataTransfer: hoverData }));
    hoverTarget = null;
    hoverData = null;
  }
  function onPointerDown(event: PointerEvent) {
    cleanup?.();
    cleanup = null;
    if (!(event.target instanceof Element)) return;
    const row = event.target.closest<HTMLElement>(SOURCE_SELECTOR);
    const button = event.target.closest('button');
    if (!row || (button && !button.matches(OPEN_BUTTON_SELECTOR))) return;
    let started = false;
    cleanup = startLoopinoReferencePointerDrag(event, row, () => {
      const data = new DataTransfer();
      const start = new DragEvent('dragstart', { bubbles: true, cancelable: true, dataTransfer: data });
      buildingPayload = true;
      started = true;
      try { row.dispatchEvent(start); } finally { buildingPayload = false; }
      if (start.defaultPrevented) return null;
      const type = PAYLOAD_TYPES.find((type) => data.types.includes(type));
      if (!type) return null;
      const raw = data.getData(type);
      if (!storagePointerDropData({ type, data: raw }, ownerAppId)) return null;
      const payload = JSON.parse(raw);
      const count = (payload.files?.length || 0) + (payload.folders?.length || 0);
      return { label: count ? `${count} Storage items` : payload.name, transfer: { type, data: raw } };
    }, (dragging) => {
      if (!dragging && started) {
        started = false;
        row.dispatchEvent(new DragEvent('dragend', { bubbles: true }));
      }
    });
  }
  function onNativeDragStart(event: DragEvent) {
    if (cleanup && !buildingPayload) { event.preventDefault(); event.stopImmediatePropagation(); }
  }
  function onMessage(event: MessageEvent) {
    if (!isExactLoopinoParentMessage(event)) return;
    const message = event.data;
    if (message?.type === 'loopino.reference-drag.leave') { leave(); return; }
    if (!['loopino.reference-drag.over', 'loopino.reference-drag.drop'].includes(message?.type)) return;
    const { x, y, transfer } = message;
    if (!Number.isFinite(x) || !Number.isFinite(y) || typeof transfer?.type !== 'string' || typeof transfer.data !== 'string') return;
    const data = storagePointerDropData(transfer, ownerAppId);
    const target = document.elementFromPoint(x, y);
    if (!data || !target?.closest('.storage-shell, .storage-sidebar-widget')) { leave(); return; }
    if (message.type === 'loopino.reference-drag.over') {
      if (hoverTarget !== target) {
        leave();
        target.dispatchEvent(new DragEvent('dragenter', { bubbles: true, cancelable: true, dataTransfer: data, clientX: x, clientY: y }));
      }
      hoverTarget = target;
      hoverData = data;
      target.dispatchEvent(new DragEvent('dragover', { bubbles: true, cancelable: true, dataTransfer: data, clientX: x, clientY: y }));
    } else {
      leave();
      target.dispatchEvent(new DragEvent('drop', { bubbles: true, cancelable: true, dataTransfer: data, clientX: x, clientY: y }));
    }
  }
  document.addEventListener('pointerdown', onPointerDown, true);
  window.addEventListener('dragstart', onNativeDragStart, true);
  window.addEventListener('message', onMessage);
  return () => {
    cleanup?.();
    leave();
    document.removeEventListener('pointerdown', onPointerDown, true);
    window.removeEventListener('dragstart', onNativeDragStart, true);
    window.removeEventListener('message', onMessage);
  };
}
