import { describe, expect, it, vi } from 'vitest';
import { callBackend, completeDriveOAuth, currentStorageAppId, driveConnectionSecretRequest, driveMediaDownloadUrl, driveMediaStreamUrl, folderMediaDownloadUrl, listDriveChildren, listDriveConnections, listDriveRoots, localizeDriveFile, LOCAL_UPLOAD_SESSION_CHUNK_BYTES, MAX_BASE64_WRITE_BYTES, moveItemsReferences, previewDriveFile, startDriveOAuth, storageBackendEndpoint, storageMediaStreamUrl, syncDriveConnection, trashDriveFile, uploadDriveFile, uploadFile } from './storageApi';

class FakeFileReader {
  onerror: ((this: FileReader, ev: ProgressEvent<FileReader>) => unknown) | null = null;
  onload: ((this: FileReader, ev: ProgressEvent<FileReader>) => unknown) | null = null;
  onprogress: ((this: FileReader, ev: ProgressEvent<FileReader>) => unknown) | null = null;
  result: string | ArrayBuffer | null = null;

  readAsDataURL(file: File) {
    void file.arrayBuffer().then((buffer) => {
      this.onprogress?.call(this as unknown as FileReader, {
        lengthComputable: true,
        loaded: file.size,
        total: file.size,
      } as ProgressEvent<FileReader>);
      this.result = `data:${file.type || 'application/octet-stream'};base64,${Buffer.from(buffer).toString('base64')}`;
      this.onload?.call(this as unknown as FileReader, {} as ProgressEvent<FileReader>);
    }).catch(() => {
      this.onerror?.call(this as unknown as FileReader, {} as ProgressEvent<FileReader>);
    });
  }
}

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

  it('syncs Drive connections with resource-scoped Drive secrets', async () => {
    const fetchImpl = vi.fn(async () => new Response(JSON.stringify({ connection_id: 'drive_conn_1', synced_files: 0 }), { status: 200 }));
    const expectedSecretRequest = driveConnectionSecretRequest('drive_conn_1');

    await syncDriveConnection('drive_conn_1', { fetchImpl });

    expect(fetchImpl).toHaveBeenCalledWith(
      '/api/apps/storage/backend',
      expect.objectContaining({
        body: JSON.stringify({
          action: 'drive_sync',
          connection_id: 'drive_conn_1',
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

  it('localizes Drive media with resource-scoped Drive secrets', async () => {
    const fetchImpl = vi.fn(async () => new Response(JSON.stringify({
      status: 'ready',
      provider: 'google_drive',
      stream_url: '/api/apps/storage/media?stable_storage_file_id=file_123',
      download_url: '/api/apps/storage/media?stable_storage_file_id=file_123&download=1',
      localization: { file_name: 'Clip.mp4' },
      file: {}
    }), { status: 200 }));
    const expectedSecretRequest = driveConnectionSecretRequest('drive_conn_1');

    const payload = await localizeDriveFile({
      id: 'file_123',
      file_id: 'file_123',
      path_id: '',
      provider: 'google_drive',
      connection_id: 'drive_conn_1',
      drive_file_id: 'file-1',
      role: '',
      name: 'Clip.mp4',
      relative_path: '',
      workspace_relative_path: '',
      extension: '.mp4',
      size_bytes: 1024,
      modified_at: '2026-05-28T00:00:00Z',
      content_type: 'video/mp4',
      preview_kind: 'video',
      sha256: ''
    }, { fetchImpl });

    expect(payload.stream_url).toBe('/api/apps/storage/media?stable_storage_file_id=file_123');
    expect(fetchImpl).toHaveBeenCalledWith(
      '/api/apps/storage/backend',
      expect.objectContaining({
        body: JSON.stringify({
          action: 'file.localize',
          connection_id: 'drive_conn_1',
          drive_file_id: 'file-1',
          stable_storage_file_id: 'file_123',
          _app_secret_request: expectedSecretRequest
        }),
        method: 'POST'
      })
    );
  });

  it('derives Drive media download URLs from stream URLs when needed', () => {
    expect(driveMediaDownloadUrl({ stream_url: '/api/apps/storage/media?stable_storage_file_id=file_123', download_url: '' }))
      .toBe('/api/apps/storage/media?stable_storage_file_id=file_123&download=1');
  });

  it('builds direct Drive media stream URLs with source version and secret selectors', () => {
    const url = driveMediaStreamUrl({
      id: 'file_123',
      file_id: 'file_123',
      path_id: '',
      provider: 'google_drive',
      connection_id: 'drive_conn_1',
      drive_file_id: 'file-1',
      role: '',
      name: 'Clip.mp4',
      relative_path: '',
      workspace_relative_path: '',
      extension: '.mp4',
      size_bytes: 1024,
      modified_at: '2026-05-28T00:00:00Z',
      content_type: 'video/mp4',
      preview_kind: 'video',
      sha256: '',
      etag_or_version: '8',
      localization_id: 'loc_123'
    }, { appId: 'storage', download: true });
    const parsed = new URL(url, 'https://example.test');
    const secretRequest = JSON.parse(parsed.searchParams.get('_app_secret_request') || '{}');

    expect(parsed.pathname).toBe('/api/apps/storage/media');
    expect(parsed.searchParams.get('stable_storage_file_id')).toBe('file_123');
    expect(parsed.searchParams.get('source_version')).toBe('8');
    expect(parsed.searchParams.get('localization_id')).toBe('loc_123');
    expect(parsed.searchParams.get('download')).toBe('1');
    expect(secretRequest).toEqual(driveConnectionSecretRequest('drive_conn_1'));
  });

  it('builds direct local file media stream URLs without provider secrets', () => {
    const url = storageMediaStreamUrl({
      id: 'file_123',
      file_id: 'file_123',
      path_id: 'generated:Videos/clip.mp4',
      provider: 'local',
      role: 'generated',
      name: 'clip.mp4',
      relative_path: 'Videos/clip.mp4',
      workspace_relative_path: 'storage/generated/Videos/clip.mp4',
      extension: '.mp4',
      size_bytes: 1024,
      modified_at: '2026-05-28T00:00:00Z',
      content_type: 'video/mp4',
      preview_kind: 'video',
      sha256: 'a'.repeat(64)
    }, { appId: 'storage', download: true });
    const parsed = new URL(url, 'https://example.test');
    const secretRequest = JSON.parse(parsed.searchParams.get('_app_secret_request') || '{}');

    expect(parsed.pathname).toBe('/api/apps/storage/media');
    expect(parsed.searchParams.get('stable_storage_file_id')).toBe('file_123');
    expect(parsed.searchParams.get('source_version')).toBe(`sha256:${'a'.repeat(64)}`);
    expect(parsed.searchParams.get('download')).toBe('1');
    expect(secretRequest).toEqual({ logical_names: [], required: false });
  });

  it('builds folder media download URLs for streamed local archives', () => {
    const url = folderMediaDownloadUrl({
      id: 'folder_123',
      provider: 'local',
      role: 'generated',
      name: 'Reports',
      relative_path: 'Reports',
      workspace_relative_path: 'storage/generated/Reports',
      modified_at: '2026-05-28T00:00:00Z'
    }, { appId: 'storage' });
    const parsed = new URL(url, 'https://example.test');
    const secretRequest = JSON.parse(parsed.searchParams.get('_app_secret_request') || '{}');

    expect(parsed.pathname).toBe('/api/apps/storage/media');
    expect(parsed.searchParams.get('media_kind')).toBe('folder');
    expect(parsed.searchParams.get('role')).toBe('generated');
    expect(parsed.searchParams.get('relative_path')).toBe('Reports');
    expect(parsed.searchParams.get('download')).toBe('1');
    expect(secretRequest).toEqual({ logical_names: [], required: false });
  });

  it('uploads files into the selected Drive folder with resource-scoped Drive secrets', async () => {
    const fetchImpl = vi.fn(async () => new Response(JSON.stringify({
      connection_id: 'drive_conn_1',
      file: {},
      provider: 'google_drive',
      status: 'uploaded',
    }), { status: 200 }));
    const expectedSecretRequest = driveConnectionSecretRequest('drive_conn_1');
    vi.stubGlobal('FileReader', FakeFileReader);

    try {
      await uploadDriveFile(
        new File(['hello'], 'notes.txt', { type: 'text/plain' }),
        { connectionId: ' drive_conn_1 ', driveFileId: ' folder-1 ' },
        { fetchImpl }
      );
    } finally {
      vi.unstubAllGlobals();
    }

    expect(fetchImpl).toHaveBeenCalledWith(
      '/api/apps/storage/backend',
      expect.objectContaining({
        body: JSON.stringify({
          action: 'drive_write',
          connection_id: 'drive_conn_1',
          parent_drive_file_id: 'folder-1',
          file_name: 'notes.txt',
          content_base64: 'aGVsbG8=',
          content_type: 'text/plain',
          _app_secret_request: expectedSecretRequest
        }),
        method: 'POST'
      })
    );
  });

  it('normalizes m4a browser uploads to audio/mp4', async () => {
    const fetchImpl = vi.fn(async () => new Response(JSON.stringify({
      file: { id: 'file_voice', file_id: 'file_voice', name: 'voice.m4a' },
      bytes_written: 5
    }), { status: 200 }));
    vi.stubGlobal('FileReader', FakeFileReader);

    try {
      await uploadFile('generated', 'Audio', new File(['voice'], 'voice.m4a', { type: '' }), { fetchImpl });
    } finally {
      vi.unstubAllGlobals();
    }

    expect(fetchImpl).toHaveBeenCalledWith(
      '/api/apps/storage/backend',
      expect.objectContaining({
        body: JSON.stringify({
          action: 'upload_file',
          role: 'generated',
          folder_relative_path: 'Audio',
          file_name: 'voice.m4a',
          content_base64: 'dm9pY2U=',
          content_type: 'audio/mp4',
          _app_secret_request: { logical_names: [], required: false }
        }),
        method: 'POST'
      })
    );
  });

  it('uses local upload sessions for files above the base64 write limit', async () => {
    const fileSize = MAX_BASE64_WRITE_BYTES + 3;
    const largeFile = {
      name: 'large.bin',
      type: 'application/octet-stream',
      size: fileSize,
      slice: (start: number, end: number) => new Blob([new Uint8Array(Math.min(16, Math.max(0, end - start))).fill(97)])
    } as unknown as File;
    const fetchImpl = vi.fn(async (_input: Parameters<typeof fetch>[0], init?: RequestInit) => {
      const body = JSON.parse(String(init?.body || '{}'));
      if (body.action === 'local_upload_session.start') {
        return new Response(JSON.stringify({
          status: 'uploading',
          provider: 'local',
          upload_session: {
            id: 'local_upload_1',
            status: 'uploading',
            provider: 'local',
            role: 'generated',
            folder_relative_path: 'Social',
            relative_path: 'Social/large.bin',
            file_name: 'large.bin',
            content_type: 'application/octet-stream',
            size_bytes: fileSize,
            bytes_uploaded: 0
          }
        }), { status: 200 });
      }
      if (body.action === 'local_upload_session.chunk') {
        const nextOffset = Math.min(fileSize, Number(body.chunk_offset) + LOCAL_UPLOAD_SESSION_CHUNK_BYTES);
        const complete = nextOffset >= fileSize;
        return new Response(JSON.stringify({
          status: complete ? 'uploaded' : 'uploading',
          provider: 'local',
          expected_offset: nextOffset,
          upload_session: {
            id: 'local_upload_1',
            status: complete ? 'complete' : 'uploading',
            provider: 'local',
            role: 'generated',
            folder_relative_path: 'Social',
            relative_path: 'Social/large.bin',
            file_name: 'large.bin',
            content_type: 'application/octet-stream',
            size_bytes: fileSize,
            bytes_uploaded: nextOffset,
            file: complete ? { id: 'file_large', file_id: 'file_large', name: 'large.bin' } : null
          },
          ...(complete ? { file: { id: 'file_large', file_id: 'file_large', name: 'large.bin' } } : {})
        }), { status: 200 });
      }
      return new Response(JSON.stringify({ detail: `Unexpected action ${body.action}` }), { status: 400 });
    });

    const payload = await uploadFile('generated', 'Social', largeFile, { fetchImpl });
    const bodies = fetchImpl.mock.calls.map((call) => JSON.parse(String(call[1]?.body || '{}')));

    expect(payload.file.id).toBe('file_large');
    expect(bodies[0]).toMatchObject({
      action: 'local_upload_session.start',
      role: 'generated',
      folder_relative_path: 'Social',
      file_name: 'large.bin',
      content_type: 'application/octet-stream',
      size_bytes: fileSize,
      _app_secret_request: { logical_names: [], required: false }
    });
    expect(bodies.slice(1).every((body) => body.action === 'local_upload_session.chunk')).toBe(true);
    expect(bodies.slice(1).every((body) => body._app_secret_request.logical_names.length === 0)).toBe(true);
    expect(bodies.some((body) => body.action === 'upload_file')).toBe(false);
  });

  it('uses Drive resumable upload sessions for files above the base64 write limit', async () => {
    const fileSize = MAX_BASE64_WRITE_BYTES + 3;
    const driveChunkBytes = 8 * 1024 * 1024;
    const largeFile = {
      name: 'large.bin',
      type: 'application/octet-stream',
      size: fileSize,
      slice: (start: number, end: number) => new Blob([new Uint8Array(Math.min(16, Math.max(0, end - start))).fill(97)])
    } as unknown as File;
    const expectedSecretRequest = driveConnectionSecretRequest('drive_conn_1');
    const fetchImpl = vi.fn(async (_input: Parameters<typeof fetch>[0], init?: RequestInit) => {
      const body = JSON.parse(String(init?.body || '{}'));
      if (body.action === 'drive_upload_session.start') {
        return new Response(JSON.stringify({
          status: 'uploading',
          provider: 'google_drive',
          connection_id: 'drive_conn_1',
          upload_session: {
            id: 'drive_upload_1',
            status: 'uploading',
            provider: 'google_drive',
            connection_id: 'drive_conn_1',
            parent_drive_file_id: 'folder-1',
            file_name: 'large.bin',
            content_type: 'application/octet-stream',
            size_bytes: fileSize,
            bytes_uploaded: 0
          }
        }), { status: 200 });
      }
      if (body.action === 'drive_upload_session.chunk') {
        const nextOffset = Math.min(fileSize, Number(body.chunk_offset) + driveChunkBytes);
        const complete = nextOffset >= fileSize;
        return new Response(JSON.stringify({
          status: complete ? 'uploaded' : 'uploading',
          provider: 'google_drive',
          connection_id: 'drive_conn_1',
          expected_offset: nextOffset,
          upload_session: {
            id: 'drive_upload_1',
            status: complete ? 'complete' : 'uploading',
            provider: 'google_drive',
            connection_id: 'drive_conn_1',
            parent_drive_file_id: 'folder-1',
            file_name: 'large.bin',
            content_type: 'application/octet-stream',
            size_bytes: fileSize,
            bytes_uploaded: nextOffset,
            file: complete ? { id: 'file_large', file_id: 'file_large', name: 'large.bin' } : null
          },
          ...(complete ? { file: { id: 'file_large', file_id: 'file_large', name: 'large.bin' } } : {})
        }), { status: 200 });
      }
      return new Response(JSON.stringify({ detail: `Unexpected action ${body.action}` }), { status: 400 });
    });

    const payload = await uploadDriveFile(
      largeFile,
      { connectionId: 'drive_conn_1', driveFileId: 'folder-1' },
      { fetchImpl }
    );
    const bodies = fetchImpl.mock.calls.map((call) => JSON.parse(String(call[1]?.body || '{}')));

    expect(payload.file.id).toBe('file_large');
    expect(bodies[0]).toMatchObject({
      action: 'drive_upload_session.start',
      connection_id: 'drive_conn_1',
      parent_drive_file_id: 'folder-1',
      file_name: 'large.bin',
      size_bytes: fileSize,
      _app_secret_request: expectedSecretRequest
    });
    expect(bodies.slice(1).every((body) => body.action === 'drive_upload_session.chunk')).toBe(true);
    expect(bodies.slice(1).every((body) => body._app_secret_request.selectors[1].resource_id === 'drive_conn_1')).toBe(true);
    expect(bodies.some((body) => body.action === 'drive_write')).toBe(false);
  });

  it('refreshes the remote Drive resumable offset after an ambiguous chunk failure', async () => {
    const fileSize = MAX_BASE64_WRITE_BYTES + 3;
    const driveChunkBytes = 8 * 1024 * 1024;
    const largeFile = {
      name: 'large.bin',
      type: 'application/octet-stream',
      size: fileSize,
      slice: (start: number, end: number) => new Blob([new Uint8Array(Math.min(16, Math.max(0, end - start))).fill(97)])
    } as unknown as File;
    let failedFirstChunk = false;
    const expectedSecretRequest = driveConnectionSecretRequest('drive_conn_1');
    const fetchImpl = vi.fn(async (_input: Parameters<typeof fetch>[0], init?: RequestInit) => {
      const body = JSON.parse(String(init?.body || '{}'));
      if (body.action === 'drive_upload_session.start') {
        return new Response(JSON.stringify({
          status: 'uploading',
          provider: 'google_drive',
          connection_id: 'drive_conn_1',
          upload_session: {
            id: 'drive_upload_1',
            status: 'uploading',
            provider: 'google_drive',
            connection_id: 'drive_conn_1',
            parent_drive_file_id: 'folder-1',
            file_name: 'large.bin',
            content_type: 'application/octet-stream',
            size_bytes: fileSize,
            bytes_uploaded: 0
          }
        }), { status: 200 });
      }
      if (body.action === 'drive_upload_session.status') {
        return new Response(JSON.stringify({
          status: 'uploading',
          provider: 'google_drive',
          connection_id: 'drive_conn_1',
          expected_offset: driveChunkBytes,
          upload_session: {
            id: 'drive_upload_1',
            status: 'uploading',
            provider: 'google_drive',
            connection_id: 'drive_conn_1',
            parent_drive_file_id: 'folder-1',
            file_name: 'large.bin',
            content_type: 'application/octet-stream',
            size_bytes: fileSize,
            bytes_uploaded: driveChunkBytes
          }
        }), { status: 200 });
      }
      if (body.action === 'drive_upload_session.chunk') {
        if (body.chunk_offset === 0 && !failedFirstChunk) {
          failedFirstChunk = true;
          return new Response(JSON.stringify({ detail: 'timeout after Drive accepted chunk' }), { status: 503 });
        }
        const nextOffset = Math.min(fileSize, Number(body.chunk_offset) + driveChunkBytes);
        const complete = nextOffset >= fileSize;
        return new Response(JSON.stringify({
          status: complete ? 'uploaded' : 'uploading',
          provider: 'google_drive',
          connection_id: 'drive_conn_1',
          expected_offset: nextOffset,
          upload_session: {
            id: 'drive_upload_1',
            status: complete ? 'complete' : 'uploading',
            provider: 'google_drive',
            connection_id: 'drive_conn_1',
            parent_drive_file_id: 'folder-1',
            file_name: 'large.bin',
            content_type: 'application/octet-stream',
            size_bytes: fileSize,
            bytes_uploaded: nextOffset,
            file: complete ? { id: 'file_large', file_id: 'file_large', name: 'large.bin' } : null
          },
          ...(complete ? { file: { id: 'file_large', file_id: 'file_large', name: 'large.bin' } } : {})
        }), { status: 200 });
      }
      return new Response(JSON.stringify({ detail: `Unexpected action ${body.action}` }), { status: 400 });
    });

    const payload = await uploadDriveFile(
      largeFile,
      { connectionId: 'drive_conn_1', driveFileId: 'folder-1' },
      { fetchImpl }
    );
    const bodies = fetchImpl.mock.calls.map((call) => JSON.parse(String(call[1]?.body || '{}')));
    const statusBody = bodies.find((body) => body.action === 'drive_upload_session.status');
    const chunkOffsets = bodies.filter((body) => body.action === 'drive_upload_session.chunk').map((body) => body.chunk_offset);

    expect(payload.file.id).toBe('file_large');
    expect(statusBody).toMatchObject({
      action: 'drive_upload_session.status',
      drive_upload_session_id: 'drive_upload_1',
      connection_id: 'drive_conn_1',
      refresh_remote: true,
      _app_secret_request: expectedSecretRequest
    });
    expect(chunkOffsets.filter((offset) => offset === 0)).toHaveLength(1);
    expect(chunkOffsets[1]).toBe(driveChunkBytes);
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
