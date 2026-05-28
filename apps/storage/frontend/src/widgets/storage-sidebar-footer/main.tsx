import { useEffect, useRef, useState } from 'react';
import type { CSSProperties, FormEvent } from 'react';
import { createRoot } from 'react-dom/client';
import { Check, FolderPlus, HardDrive, Upload, X } from 'lucide-react';
import { createFolder, currentStorageAppId, loadCatalog, startDriveOAuth, uploadFile } from '../../storageApi';
import { roleLabels } from '../../storageMeta';
import { storageSelectionFromMessage, type ActiveStorageSelectionMessage } from '../../lib/activeStorageSelection';
import { applyStorageFoldersDelta } from '../../lib/storageCatalogDelta';
import { storageTargetFromWidgetContext, type StorageNavigationTarget } from '../../lib/storageNavigationParams';
import { storageOAuthRedirectUri } from '../../lib/storageOAuthRuntime';
import type { FileRole, StorageFile, StorageFolder } from '../../types';
import '../../styles/sidebar-widget.css';

const PRIMARY_ACTION_LABEL = 'New Folder';
const WIDGET_ID = 'storage-sidebar-footer';

type FolderActionTarget = {
  relativePath: string;
  role: FileRole;
  workspaceRelativePath: string;
};

function isFileRole(role: unknown): role is FileRole {
  return role === 'uploaded' || role === 'generated';
}

function parentFolderPath(relativePath: string) {
  const parts = relativePath.split('/').filter(Boolean);
  parts.pop();
  return parts.join('/');
}

function targetFromFolder(folder: StorageFolder): FolderActionTarget {
  if (!isFileRole(folder.role)) {
    throw new Error('Folder actions require a local Storage folder.');
  }
  return {
    relativePath: folder.relative_path,
    role: folder.role,
    workspaceRelativePath: folder.workspace_relative_path
  };
}

function targetFromNavigationTarget(target: StorageNavigationTarget | null): FolderActionTarget | null {
  if (!target || target.targetType !== 'folder' || !isFileRole(target.role)) {
    return null;
  }
  const relativePath = target.folderRelativePath || '';
  return {
    relativePath,
    role: target.role,
    workspaceRelativePath: relativePath ? `storage/${target.role}/${relativePath}` : `storage/${target.role}`
  };
}

function targetLabel(target: FolderActionTarget | null) {
  if (!target) {
    return 'Choose Uploaded or Generated first';
  }
  return `${roleLabels[target.role]}${target.relativePath ? ` / ${target.relativePath}` : ''}`;
}

function nextDefaultFolderName(target: FolderActionTarget, folders: StorageFolder[]) {
  const siblingNames = new Set(
    folders
      .filter((folder) => folder.role === target.role && parentFolderPath(folder.relative_path) === target.relativePath)
      .map((folder) => folder.name.toLowerCase())
  );
  const baseName = 'New Folder';
  if (!siblingNames.has(baseName.toLowerCase())) {
    return baseName;
  }
  for (let index = 2; index < 1000; index += 1) {
    const candidate = `${baseName} ${index}`;
    if (!siblingNames.has(candidate.toLowerCase())) {
      return candidate;
    }
  }
  return `${baseName} ${Date.now()}`;
}

function openFolderInShell(appId: string, target: FolderActionTarget) {
  window.parent?.postMessage(
    {
      type: 'maverick.widget.open-app',
      app_id: appId,
      params: {
        folder_relative_path: target.relativePath,
        role: target.role
      }
    },
    window.location.origin
  );
}

function openFileInShell(appId: string, file: StorageFile) {
  window.parent?.postMessage(
    {
      type: 'maverick.widget.open-app',
      app_id: appId,
      params: {
        workspace_relative_path: file.workspace_relative_path
      }
    },
    window.location.origin
  );
}

function postStorageFilesChanged(appId: string) {
  window.parent?.postMessage(
    {
      type: 'maverick.app.data-changed',
      owner_app_id: appId,
      resource: 'files'
    },
    window.location.origin
  );
}

function postPrimaryActionState(appId: string, available: boolean) {
  window.parent?.postMessage(
    {
      type: 'maverick.widget.primary-action.state',
      owner_app_id: appId,
      widget_id: WIDGET_ID,
      available,
      label: PRIMARY_ACTION_LABEL,
      preferred_surface: 'sidebar'
    },
    window.location.origin
  );
}

function StorageSidebarFooterWidget() {
  const appId = currentStorageAppId();
  const [folders, setFolders] = useState<StorageFolder[]>([]);
  const [target, setTarget] = useState<FolderActionTarget | null>(null);
  const [newFolderName, setNewFolderName] = useState('');
  const [isNamingFolder, setIsNamingFolder] = useState(false);
  const [isCreatingFolder, setIsCreatingFolder] = useState(false);
  const [isConnectingDrive, setIsConnectingDrive] = useState(false);
  const [isUploading, setIsUploading] = useState(false);
  const [uploadLabel, setUploadLabel] = useState('');
  const [uploadProgress, setUploadProgress] = useState(0);
  const [status, setStatus] = useState('');
  const folderNameInputRef = useRef<HTMLInputElement | null>(null);
  const uploadInputRef = useRef<HTMLInputElement | null>(null);

  async function refreshCatalog() {
    const payload = await loadCatalog({ limit: 1, offset: 0 });
    setFolders(payload.folders || []);
  }

  function revalidateCatalog() {
    refreshCatalog().catch((loadError: Error) => setStatus(loadError.message));
  }

  useEffect(() => {
    refreshCatalog().catch((loadError: Error) => setStatus(loadError.message));
  }, []);

  useEffect(() => {
    if (isNamingFolder) {
      folderNameInputRef.current?.select();
    }
  }, [isNamingFolder]);

  useEffect(() => {
    function handleShellMessage(event: MessageEvent) {
      if (event.origin !== window.location.origin || !event.data || typeof event.data !== 'object') {
        return;
      }
      const payload = event.data as {
        owner_app_id?: string;
        resource?: string;
        type?: string;
      } & ActiveStorageSelectionMessage;
      const contextTarget = targetFromNavigationTarget(storageTargetFromWidgetContext(payload));
      if (contextTarget) {
        setTarget(contextTarget);
        setStatus('');
        return;
      }
      const activeTarget = targetFromNavigationTarget(storageSelectionFromMessage(payload));
      if (activeTarget) {
        setTarget(activeTarget);
        setStatus('');
        return;
      }
      if (payload.type !== 'maverick.widget.data-changed' || payload.owner_app_id !== appId) {
        return;
      }
      if (payload.resource === 'files') {
        void refreshCatalog();
      }
    }

    window.addEventListener('message', handleShellMessage);
    return () => window.removeEventListener('message', handleShellMessage);
  }, [appId]);

  function requireTarget(action: 'create' | 'upload') {
    if (target) {
      return target;
    }
    setStatus(`Choose Uploaded or Generated before ${action === 'create' ? 'creating a folder' : 'uploading a file'}.`);
    return null;
  }

  function startNewFolder() {
    const nextTarget = requireTarget('create');
    if (!nextTarget) {
      return;
    }
    setNewFolderName(nextDefaultFolderName(nextTarget, folders));
    setIsNamingFolder(true);
    setStatus('');
  }

  async function submitNewFolder(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const nextTarget = requireTarget('create');
    if (!nextTarget) {
      return;
    }
    const folderName = newFolderName.trim();
    if (!folderName) {
      setStatus('Folder name is required.');
      return;
    }
    setIsCreatingFolder(true);
    try {
      const payload = await createFolder(nextTarget.role, nextTarget.relativePath, folderName);
      const createdTarget = targetFromFolder(payload.folder);
      setFolders((current) => applyStorageFoldersDelta(current, { type: 'upsert_folder', folder: payload.folder }));
      revalidateCatalog();
      setTarget(createdTarget);
      setIsNamingFolder(false);
      setNewFolderName('');
      setStatus('');
      openFolderInShell(appId, createdTarget);
    } catch (createError) {
      setStatus(createError instanceof Error ? createError.message : 'Unable to create folder.');
    } finally {
      setIsCreatingFolder(false);
    }
  }

  function requestUpload() {
    if (!requireTarget('upload')) {
      return;
    }
    uploadInputRef.current?.click();
  }

  async function connectDrive() {
    const authorizationWindow = openBlankAuthorizationWindow();
    setIsConnectingDrive(true);
    setStatus('');
    try {
      const payload = await startDriveOAuth({ redirectUri: storageOAuthRedirectUri(appId, window.location.origin) });
      if (payload.status === 'not_configured') {
        closeAuthorizationWindow(authorizationWindow);
        setStatus('Google Drive OAuth is not configured');
        return;
      }
      if (!payload.authorization_url) {
        closeAuthorizationWindow(authorizationWindow);
        setStatus('Google Drive authorization could not be started.');
        return;
      }
      openAuthorizationUrl(payload.authorization_url, authorizationWindow);
    } catch (connectError) {
      closeAuthorizationWindow(authorizationWindow);
      setStatus(connectError instanceof Error ? connectError.message : 'Unable to connect Google Drive.');
    } finally {
      setIsConnectingDrive(false);
    }
  }

  async function uploadSelectedFiles(selectedFiles: File[]) {
    if (!selectedFiles.length) {
      return;
    }
    const nextTarget = requireTarget('upload');
    if (!nextTarget) {
      return;
    }
    setIsUploading(true);
    setUploadLabel(selectedFiles.length === 1 ? selectedFiles[0].name : `${selectedFiles.length} files`);
    setUploadProgress(0);
    try {
      let uploadedFile: StorageFile | null = null;
      for (let index = 0; index < selectedFiles.length; index += 1) {
        const file = selectedFiles[index];
        setUploadLabel(file.name);
        const payload = await uploadFile(nextTarget.role, nextTarget.relativePath, file, {
          onProgress: (progress) => {
            const aggregateProgress = ((index + (progress.percent / 100)) / selectedFiles.length) * 100;
            setUploadProgress(Math.max(1, Math.min(99, Math.round(aggregateProgress))));
          }
        });
        uploadedFile = payload.file;
        setUploadProgress(Math.round(((index + 1) / selectedFiles.length) * 100));
      }
      revalidateCatalog();
      setStatus('');
      postStorageFilesChanged(appId);
      if (uploadedFile) {
        openFileInShell(appId, uploadedFile);
      } else {
        openFolderInShell(appId, nextTarget);
      }
    } catch (uploadError) {
      setStatus(uploadError instanceof Error ? uploadError.message : 'Upload failed.');
    } finally {
      setIsUploading(false);
      setUploadLabel('');
      setUploadProgress(0);
    }
  }

  const currentTargetLabel = targetLabel(target);
  const actionDisabled = !target || isCreatingFolder || isUploading;
  const driveConnectDisabled = isConnectingDrive || isUploading || isCreatingFolder;
  const primaryActionAvailable = !actionDisabled && !isNamingFolder;

  useEffect(() => {
    postPrimaryActionState(appId, primaryActionAvailable);
  }, [appId, primaryActionAvailable]);

  useEffect(() => {
    function handlePrimaryActionMessage(event: MessageEvent) {
      if (event.origin !== window.location.origin || !event.data || typeof event.data !== 'object') {
        return;
      }
      const payload = event.data as { owner_app_id?: string; type?: string; widget_id?: string };
      if (payload.owner_app_id !== appId || payload.widget_id !== WIDGET_ID) {
        return;
      }
      if (payload.type === 'maverick.widget.primary-action.query') {
        postPrimaryActionState(appId, primaryActionAvailable);
        return;
      }
      if (payload.type === 'maverick.widget.primary-action.invoke' && primaryActionAvailable) {
        startNewFolder();
      }
    }
    window.addEventListener('message', handlePrimaryActionMessage);
    return () => window.removeEventListener('message', handlePrimaryActionMessage);
  }, [appId, folders, primaryActionAvailable, target]);

  return (
    <main className="storage-sidebar-footer-widget">
      {status ? (
        <button className="storage-sidebar-footer-status is-visible" onClick={() => setStatus('')} title={status} type="button">
          {status}
        </button>
      ) : (
        <span className="storage-sidebar-footer-status" aria-live="polite" />
      )}
      {isUploading ? (
        <div
          aria-label={`Uploading ${uploadLabel || 'file'} ${uploadProgress}%`}
          className="storage-sidebar-footer-uploading"
          role="status"
          style={{ '--storage-upload-progress': `${uploadProgress}%` } as CSSProperties}
        >
          <span className="storage-sidebar-upload-skeleton" aria-hidden="true">
            <span className="storage-sidebar-upload-skeleton__icon" />
            <span className="storage-sidebar-upload-skeleton__copy">
              <span />
              <span />
            </span>
          </span>
          <span className="storage-sidebar-upload-progress" aria-hidden="true">
            <span>{uploadProgress}%</span>
          </span>
        </div>
      ) : isNamingFolder ? (
        <form className="storage-sidebar-footer-actions is-naming" onSubmit={submitNewFolder}>
          <input
            aria-label="New folder name"
            onChange={(event) => setNewFolderName(event.target.value)}
            ref={folderNameInputRef}
            value={newFolderName}
          />
          <button aria-label="Create folder" disabled={isCreatingFolder} title={`Create in ${currentTargetLabel}`} type="submit">
            <Check aria-hidden="true" className="storage-sidebar-footer-icon" />
          </button>
          <button
            aria-label="Cancel new folder"
            disabled={isCreatingFolder}
            onClick={() => {
              setIsNamingFolder(false);
              setNewFolderName('');
            }}
            type="button"
          >
            <X aria-hidden="true" className="storage-sidebar-footer-icon" />
          </button>
        </form>
      ) : (
        <div className="storage-sidebar-footer-actions">
          <input
            className="storage-sidebar-footer-upload-input"
            multiple
            onChange={(event) => {
              const selected = Array.from(event.currentTarget.files || []);
              event.currentTarget.value = '';
              void uploadSelectedFiles(selected);
            }}
            ref={uploadInputRef}
            type="file"
          />
          <button
            className="storage-sidebar-footer-button"
            disabled={actionDisabled}
            onClick={startNewFolder}
            title={`Create a folder in ${currentTargetLabel}`}
            type="button"
          >
            <FolderPlus aria-hidden="true" className="storage-sidebar-footer-icon" />
            <span>New Folder</span>
          </button>
          <button
            aria-label={`Upload files to ${currentTargetLabel}`}
            className="storage-sidebar-footer-button storage-sidebar-footer-button--icon"
            disabled={actionDisabled}
            onClick={requestUpload}
            title={`Upload files to ${currentTargetLabel}`}
            type="button"
          >
            <Upload aria-hidden="true" className="storage-sidebar-footer-icon" />
          </button>
          <button
            aria-label={isConnectingDrive ? 'Connecting Google Drive' : 'Connect Drive'}
            className="storage-sidebar-footer-button storage-sidebar-footer-button--icon"
            disabled={driveConnectDisabled}
            onClick={() => connectDrive()}
            title={isConnectingDrive ? 'Connecting Google Drive' : 'Connect Google Drive'}
            type="button"
          >
            <HardDrive aria-hidden="true" className="storage-sidebar-footer-icon" />
          </button>
        </div>
      )}
    </main>
  );
}

function openBlankAuthorizationWindow() {
  const popup = window.open('about:blank', '_blank');
  if (!popup) {
    return null;
  }
  try {
    popup.document.title = 'Opening Google Drive';
    popup.document.body.style.fontFamily = 'system-ui, sans-serif';
    popup.document.body.style.padding = '24px';
    popup.document.body.textContent = 'Opening Google Drive...';
  } catch {
    return popup;
  }
  return popup;
}

function openAuthorizationUrl(authorizationUrl: string, popup: Window | null) {
  if (popup && !popup.closed) {
    popup.location.replace(authorizationUrl);
    try {
      popup.opener = null;
      popup.focus();
    } catch {
      return;
    }
    return;
  }
  if (window.top && window.top !== window) {
    window.parent.postMessage({ type: 'maverick.app.external-url', url: authorizationUrl }, window.location.origin);
    return;
  }
  window.location.assign(authorizationUrl);
}

function closeAuthorizationWindow(popup: Window | null) {
  if (popup && !popup.closed) {
    try {
      popup.close();
    } catch {
      return;
    }
  }
}

createRoot(document.getElementById('storage-sidebar-footer-root') as HTMLElement).render(<StorageSidebarFooterWidget />);
