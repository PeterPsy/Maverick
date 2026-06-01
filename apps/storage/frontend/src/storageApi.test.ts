import { describe, expect, it, vi } from 'vitest';
import { callBackend, completeDriveOAuth, currentStorageAppId, driveConnectionSecretRequest, listDriveChildren, listDriveConnections, listDriveRoots, moveItemsReferences, previewDriveFile, startDriveOAuth, storageBackendEndpoint, trashDriveFile } from './storageApi';

describe('storage api client', () => {
  it('derives the mounted app backend from app and widget routes', () => {
    expect(currentStorageAppId('/apps/storage-fork/')).toBe('storage-fork');
    expect(currentStorageAppId('/api/apps/widgets/storage-fork/storage-sidebar-footer/frontend/')).toBe('storage-fork');
    expect(currentStorageAppId('/app/storage/files')).toBe('storage');
    expect(storageBackendEndpoint('storage-fork')).toBe('/api/apps/storage-fork/backend');
  });

  it('calls the selected app backend endpoint', async () => {
    const fetchImpl = vi.fn(async () => new Response(JSON.stringify({ ok: true }), { status: 200 }));

    await expect(callBackend<{ ok: boolean }>({ action: 'catalog' }, { appId: 'storage-fork', fetchImpl })).resolves.toEqual({ ok: true });
    expect(fetchImpl).toHaveBeenCalledWith(
      '/api/apps/storage-fork/backend',
      expect.objectContaining({
        body: JSON.stringify({ action: 'catalog', _app_secret_request: { logical_names: [], required: false } }),
        method: 'POST'
      })
    );
  });

  it('preserves explicit app secret requests for provider actions', async () => {
    const fetchImpl = vi.fn(async () => new Response(JSON.stringify({ ok: true }), { status: 200 }));
    const secretRequest = {
      selectors: [
        { logical_names: ['google-drive-oauth-client-id', 'google-drive-oauth-client-secret'] },
        { logical_names: ['google-drive-refresh-token'], resource_type: 'drive_connection', resource_id: 'drive_conn_1' }
      ],
      required: true
    };

    await callBackend<{ ok: boolean }>({ action: 'drive_list_roots', _app_secret_request: secretRequest }, { fetchImpl });

    expect(fetchImpl).toHaveBeenCalledWith(
      '/api/apps/storage/backend',
      expect.objectContaining({
        body: JSON.stringify({ action: 'drive_list_roots', _app_secret_request: secretRequest }),
        method: 'POST'
      })
    );
  });

  it('lists Drive connections without requesting refresh tokens', async () => {
    const fetchImpl = vi.fn(async () => new Response(JSON.stringify({ connections: [], provider: 'google_drive' }), { status: 200 }));

    await listDriveConnections({ fetchImpl });

    expect(fetchImpl).toHaveBeenCalledWith(
      '/api/apps/storage/backend',
      expect.objectContaining({
        body: JSON.stringify({ action: 'drive_connections.list', _app_secret_request: {} }),
        method: 'POST'
      })
    );
  });

  it('starts Drive OAuth with the OAuth client id, client secret, and redirect URL', async () => {
    const fetchImpl = vi.fn(async () => new Response(JSON.stringify({ provider: 'google_drive', status: 'not_configured' }), { status: 200 }));

    await startDriveOAuth({ fetchImpl, redirectUri: 'https://maverick.local/apps/storage/oauth/callback' });

    expect(fetchImpl).toHaveBeenCalledWith(
      '/api/apps/storage/backend',
      expect.objectContaining({
        body: JSON.stringify({
          action: 'drive_connections.start_oauth',
          redirect_uri: 'https://maverick.local/apps/storage/oauth/callback',
          _app_secret_request: {
            logical_names: ['google-drive-oauth-client-id', 'google-drive-oauth-client-secret'],
            required: false
          }
        }),
        method: 'POST'
      })
    );
  });

  it('completes Drive OAuth with required OAuth client credentials', async () => {
    const fetchImpl = vi.fn(async () => new Response(JSON.stringify({
      access_mode: 'full_rw',
      connection: { id: 'drive_conn_1' },
      connection_id: 'drive_conn_1',
      provider: 'google_drive',
      status: 'connected',
    }), { status: 200 }));

    await completeDriveOAuth({
      code: 'auth-code',
      redirectUri: 'https://maverick.local/apps/storage/oauth/callback',
      state: 'drive-state',
    }, { fetchImpl });

    expect(fetchImpl).toHaveBeenCalledWith(
      '/api/apps/storage/backend',
      expect.objectContaining({
        body: JSON.stringify({
          action: 'drive_connections.complete_oauth',
          provider: 'google_drive',
          code: 'auth-code',
          state: 'drive-state',
          redirect_uri: 'https://maverick.local/apps/storage/oauth/callback',
          _app_secret_request: {
            logical_names: ['google-drive-oauth-client-id', 'google-drive-oauth-client-secret'],
            required: true
          }
        }),
        method: 'POST'
      })
    );
  });

  it('rejects incomplete Drive OAuth completion responses', async () => {
    const fetchImpl = vi.fn(async () => new Response(JSON.stringify({
      access_mode: 'full_rw',
      provider: 'google_drive',
      status: 'needs_secret_grant',
    }), { status: 200 }));

    await expect(completeDriveOAuth({
      code: 'auth-code',
      redirectUri: 'https://maverick.local/apps/storage/oauth/callback',
      state: 'drive-state',
    }, { fetchImpl })).rejects.toThrow('Google Drive connection failed.');
  });

  it('uses resource-scoped selectors for connected Drive folder actions', async () => {
    const fetchImpl = vi.fn(async () => new Response(JSON.stringify({ files: [], folders: [], provider: 'google_drive', connection_id: 'drive_conn_1' }), { status: 200 }));
    const expectedSecretRequest = driveConnectionSecretRequest('drive_conn_1');

    await listDriveRoots('drive_conn_1', { fetchImpl });
    await listDriveChildren('drive_conn_1', 'folder-1', { fetchImpl });

    expect(fetchImpl).toHaveBeenNthCalledWith(
      1,
      '/api/apps/storage/backend',
      expect.objectContaining({
        body: JSON.stringify({
          action: 'drive_list_roots',
          connection_id: 'drive_conn_1',
          _app_secret_request: expectedSecretRequest
        }),
        method: 'POST'
      })
    );
    expect(fetchImpl).toHaveBeenNthCalledWith(
      2,
      '/api/apps/storage/backend',
      expect.objectContaining({
        body: JSON.stringify({
          action: 'drive_list_children',
          connection_id: 'drive_conn_1',
          drive_file_id: 'folder-1',
          _app_secret_request: expectedSecretRequest
        }),
        method: 'POST'
      })
    );
  });

  it('passes Drive list limits and page tokens to the backend', async () => {
    const fetchImpl = vi.fn(async () => new Response(JSON.stringify({ files: [], folders: [], provider: 'google_drive', connection_id: 'drive_conn_1' }), { status: 200 }));
    const expectedSecretRequest = driveConnectionSecretRequest('drive_conn_1');

    await listDriveChildren('drive_conn_1', 'folder-1', { fetchImpl, limit: 500, pageToken: 'next-token' });

    expect(fetchImpl).toHaveBeenCalledWith(
      '/api/apps/storage/backend',
      expect.objectContaining({
        body: JSON.stringify({
          action: 'drive_list_children',
          connection_id: 'drive_conn_1',
          drive_file_id: 'folder-1',
          limit: 500,
          page_token: 'next-token',
          _app_secret_request: expectedSecretRequest
        }),
        method: 'POST'
      })
    );
  });

  it('passes abort signals to backend fetch calls', async () => {
    const fetchImpl = vi.fn(async () => new Response(JSON.stringify({ files: [], folders: [], provider: 'google_drive', connection_id: 'drive_conn_1' }), { status: 200 }));
    const controller = new AbortController();

    await listDriveChildren('drive_conn_1', 'folder-1', { fetchImpl, signal: controller.signal });

    expect(fetchImpl).toHaveBeenCalledWith(
      '/api/apps/storage/backend',
      expect.objectContaining({
        method: 'POST',
        signal: controller.signal
      })
    );
  });

  it('confirms Drive trash requests after UI confirmation', async () => {
    const fetchImpl = vi.fn(async () => new Response(JSON.stringify({ file: {}, status: 'trashed' }), { status: 200 }));
    const expectedSecretRequest = driveConnectionSecretRequest('drive_conn_1');

    await trashDriveFile({
      id: 'drive:file-1',
      file_id: 'stable-file-1',
      path_id: 'drive:file-1',
      provider: 'google_drive',
      connection_id: 'drive_conn_1',
      drive_file_id: 'file-1',
      role: '',
      name: 'Report.docx',
      relative_path: 'Report.docx',
      workspace_relative_path: 'drive/Report.docx',
      extension: '.docx',
      size_bytes: 10,
      modified_at: '2026-05-28T00:00:00Z',
      content_type: 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
      preview_kind: 'document',
      sha256: ''
    }, { fetchImpl });

    expect(fetchImpl).toHaveBeenCalledWith(
      '/api/apps/storage/backend',
      expect.objectContaining({
        body: JSON.stringify({
          action: 'drive_trash',
          connection_id: 'drive_conn_1',
          drive_file_id: 'file-1',
          stable_storage_file_id: 'stable-file-1',
          confirm: true,
          delete_policy: 'user_confirmed',
          _app_secret_request: expectedSecretRequest
        }),
        method: 'POST'
      })
    );
  });

  it('requests Drive previews with resource-scoped Drive secrets', async () => {
    const fetchImpl = vi.fn(async () => new Response(JSON.stringify({ file: {}, preview_text: 'Preview' }), { status: 200 }));
    const expectedSecretRequest = driveConnectionSecretRequest('drive_conn_1');

    await previewDriveFile({
      id: 'file_123',
      file_id: 'file_123',
      path_id: '',
      provider: 'google_drive',
      connection_id: 'drive_conn_1',
      drive_file_id: 'file-1',
      role: '',
      name: 'Plan',
      relative_path: '',
      workspace_relative_path: '',
      extension: '',
      size_bytes: 0,
      modified_at: '2026-05-28T00:00:00Z',
      content_type: 'application/vnd.google-apps.document',
      preview_kind: 'document',
      sha256: ''
    }, 8192, 1200, { fetchImpl });

    expect(fetchImpl).toHaveBeenCalledWith(
      '/api/apps/storage/backend',
      expect.objectContaining({
        body: JSON.stringify({
          action: 'drive_preview',
          connection_id: 'drive_conn_1',
          drive_file_id: 'file-1',
          stable_storage_file_id: 'file_123',
          max_bytes: 8192,
          max_chars: 1200,
          _app_secret_request: expectedSecretRequest
        }),
        method: 'POST'
      })
    );
  });

  it('sends selected file and folder moves as one backend action', async () => {
    const fetchImpl = vi.fn(async () => new Response(JSON.stringify({ files: [], folders: [] }), { status: 200 }));
    vi.stubGlobal('fetch', fetchImpl);

    try {
      await moveItemsReferences(
        [{ role: 'generated', relative_path: 'loose.md', workspace_relative_path: 'storage/generated/loose.md' }],
        [{ role: 'generated', relative_path: 'Reports', workspace_relative_path: 'storage/generated/Reports' }],
        'generated',
        'Archive'
      );
    } finally {
      vi.unstubAllGlobals();
    }

    expect(fetchImpl).toHaveBeenCalledWith(
      '/api/apps/storage/backend',
      expect.objectContaining({
        body: JSON.stringify({
          action: 'move_items',
          role: 'generated',
          target_folder_relative_path: 'Archive',
          files: [{ role: 'generated', relative_path: 'loose.md', workspace_relative_path: 'storage/generated/loose.md' }],
          folders: [{ role: 'generated', relative_path: 'Reports', workspace_relative_path: 'storage/generated/Reports' }],
          _app_secret_request: { logical_names: [], required: false }
        }),
        method: 'POST'
      })
    );
  });
});
