import { useState, type DragEvent } from 'react';
import { createRoot } from 'react-dom/client';
import { AnimatedFileCollection } from '../../../../storage/frontend/src/components/ui/animated-collection';
import { installStoragePointerDrags } from '../../../../storage/frontend/src/lib/storagePointerDrag';
import {
  storageDragPayloadFromFile, storageDragPayloadFromFolder, storageDragPayloadFromSelection,
  storageDriveDragPayloadFromFile, storageDriveDragPayloadFromFolder, storageMoveDropStatus,
  writeStorageFileDragData, writeStorageFolderDragData, writeStorageSelectionDragData,
  writeStorageDriveFileDragData, writeStorageDriveFolderDragData,
  readStorageFileDragData, readStorageFolderDragData, readStorageSelectionDragData,
} from '../../../../storage/frontend/src/lib/storageDragDrop';
import type { StorageFile, StorageFolder } from '../../../../storage/frontend/src/types';
import '../../../../storage/frontend/src/styles/main.css';

const params = new URLSearchParams(location.search);
const mode = params.get('mode') || 'file';
const targetRole = params.get('target_role') === 'generated' ? 'generated' : 'uploaded';
Object.defineProperty(window, '__LOOPINO_PLATFORM_ORIGIN__', { value: params.get('shell_origin') });
installStoragePointerDrags('storage');
const file: StorageFile = {
  id: 'file-fixture', file_id: 'file-fixture', path_id: 'file-fixture', name: 'Synthetic document.txt',
  relative_path: 'Synthetic document.txt', workspace_relative_path: 'storage/uploaded/Synthetic document.txt', role: 'uploaded',
  preview_kind: 'text', content_type: 'text/plain', modified_at: '2026-10-11T12:00:00Z', size_bytes: 32, sha256: '', extension: '.txt',
  ...(mode === 'drive-file' ? { provider: 'google_drive' as const, role: '' as const, connection_id: 'drive-fixture', drive_file_id: 'remote-file', file_id: 'drive-file-fixture' } : {}),
};
const folder: StorageFolder = {
  id: 'folder-fixture', name: 'Synthetic folder', relative_path: 'Synthetic folder',
  workspace_relative_path: 'storage/uploaded/Synthetic folder', role: 'uploaded', modified_at: file.modified_at,
  ...(mode === 'drive-folder' ? { provider: 'google_drive' as const, role: '' as const, connection_id: 'drive-fixture', drive_file_id: 'remote-folder' } : {}),
};

function Fixture() {
  const [opened, setOpened] = useState(0);
  const [actions, setActions] = useState(0);
  const [moves, setMoves] = useState<unknown[]>([]);
  const [hover, setHover] = useState('none');
  const open = () => setOpened((count) => count + 1);
  const action = () => setActions((count) => count + 1);
  function writeFolder(event: DragEvent<HTMLElement>) {
    if (mode === 'drive-folder') writeStorageDriveFolderDragData(event.dataTransfer, storageDriveDragPayloadFromFolder(folder, 'storage')!);
    else writeStorageFolderDragData(event.dataTransfer, storageDragPayloadFromFolder(folder, 'storage'));
  }
  return (
    <main className={mode === 'sidebar' ? 'storage-sidebar-widget' : 'storage-shell'} style={{ padding: 12, display: 'block' }}>
      {mode === 'sidebar' || mode.includes('folder') ? (
        <article className="folder-card" draggable onDragStart={writeFolder} style={{ marginBottom: 20 }}>
          <button className="folder-card-open" onClick={open}>Synthetic folder</button>
          <button className="folder-card-action" onClick={action}>Details</button>
        </article>
      ) : (
        <AnimatedFileCollection files={[file]} onOpen={open} onDelete={action} onDownload={action}
          onShowDetails={action} onLongPress={() => undefined} onToggleSelection={() => undefined}
          onDragEnd={() => undefined} view="list" selectionMode={mode === 'selection'}
          selectedFileIds={new Set(mode === 'selection' ? [file.id] : [])} draggingFileIds={new Set()}
          onDragStart={(event) => {
            if (mode === 'selection') writeStorageSelectionDragData(event.dataTransfer, storageDragPayloadFromSelection({ files: [file], folders: [folder] }, 'storage'));
            else if (mode === 'drive-file') writeStorageDriveFileDragData(event.dataTransfer, storageDriveDragPayloadFromFile(file, 'storage')!);
            else writeStorageFileDragData(event.dataTransfer, storageDragPayloadFromFile(file, 'storage'));
            return mode === 'selection' ? 2 : 1;
          }} />
      )}
      <div data-testid="move-target" className="folder-card" style={{ height: 100, marginTop: 30 }}
        onDragOver={(event) => { event.preventDefault(); setHover(storageMoveDropStatus(event.dataTransfer, targetRole)); }}
        onDragLeave={() => setHover('none')}
        onDrop={(event) => {
          event.preventDefault();
          const selection = readStorageSelectionDragData(event.dataTransfer, 'storage');
          const sourceFile = readStorageFileDragData(event.dataTransfer, 'storage');
          const sourceFolder = readStorageFolderDragData(event.dataTransfer, 'storage');
          if (storageMoveDropStatus(event.dataTransfer, targetRole) === 'ready') setMoves((current) => [...current, selection || sourceFile || sourceFolder]);
          setHover('none');
        }}>Move target</div>
      <output data-testid="opened">{opened}</output><output data-testid="actions">{actions}</output>
      <output data-testid="moves">{JSON.stringify(moves)}</output><output data-testid="hover">{hover}</output>
    </main>
  );
}
createRoot(document.getElementById('root')!).render(<Fixture />);
