import { afterEach, describe, expect, it, vi } from 'vitest';
import { bootstrapApp, callStorageBackend, openStorageForMedia, openStorageVideoPicker, startWorkout, storageMediaSelectionFromPickerParams, storageNavigationParamsForMedia, storageVideoPickerNavigationParamsForMedia } from './api';
import type { ExerciseMediaRef, StorageFolderRef } from './types';

function jsonResponse(payload: unknown, ok = true) {
  return {
    ok,
    status: ok ? 200 : 500,
    json: async () => payload
  } as Response;
}

const localMedia: Extract<ExerciseMediaRef, { kind: 'local_file' }> = {
  kind: 'local_file',
  provider: 'local',
  file_id: 'file_local',
  workspace_relative_path: 'storage/uploaded/workout/video.png',
  display_path: 'storage/uploaded/workout/video.png',
  name: 'video.png',
  content_type: 'image/png',
  preview_kind: 'image'
};

const driveMedia: Extract<ExerciseMediaRef, { kind: 'drive_file' }> = {
  kind: 'drive_file',
  provider: 'google_drive',
  stable_storage_file_id: 'file_drive',
  connection_id: 'drive_conn',
  drive_file_id: 'drive_file',
  display_path: '/My Drive/workout/video.mp4',
  name: 'video.mp4',
  content_type: 'video/mp4',
  preview_kind: 'video'
};

const driveFolder: Extract<StorageFolderRef, { kind: 'drive_folder' }> = {
  kind: 'drive_folder',
  provider: 'google_drive',
  connection_id: 'drive_conn',
  drive_file_id: 'folder_drive',
  display_path: '/My Drive/workout'
};

describe('Storage integration API', () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it('declares catalog calls as Storage requests without secret delivery', async () => {
    const fetchMock = vi.fn(async (_input: RequestInfo | URL, _init?: RequestInit) => jsonResponse({ files: [] }));
    vi.stubGlobal('fetch', fetchMock);

    await callStorageBackend({ action: 'catalog', role: 'all', kind: 'video', limit: 80 });

    const [, init] = fetchMock.mock.calls[0];
    const body = JSON.parse(String(init?.body));
    expect(body).toMatchObject({
      action: 'catalog',
      kind: 'video',
      _app_secret_request: {
        logical_names: [],
        required: false
      }
    });
  });

  it('preserves explicit Storage secret requests for Drive operations', async () => {
    const fetchMock = vi.fn(async (_input: RequestInfo | URL, _init?: RequestInit) => jsonResponse({ status: 'ok' }));
    vi.stubGlobal('fetch', fetchMock);
    const secretRequest = {
      required: true,
      selectors: [{ logical_names: ['google-drive-refresh-token'], resource_type: 'drive_connection', resource_id: 'drive_conn' }]
    };

    await callStorageBackend({ action: 'file.localize', _app_secret_request: secretRequest });

    const [, init] = fetchMock.mock.calls[0];
    const body = JSON.parse(String(init?.body));
    expect(body._app_secret_request).toEqual(secretRequest);
  });

  it('loads the frontend bootstrap in one backend action without runs on the critical path', async () => {
    const fetchMock = vi.fn(async (_input: RequestInfo | URL, _init?: RequestInit) => jsonResponse({
      workspace_id: 'default',
      app_id: 'fitness-coach',
      state_version: '1:now:1:1:0',
      workouts: [],
      workout_summaries: [],
      selected_workout: null,
      exercises: [],
      tags: [],
      runs: [],
      view_state: { selected_workout_id: null, setup_tab: 'workout-settings', sidebar_query: '' }
    }));
    vi.stubGlobal('fetch', fetchMock);

    await bootstrapApp({ includeRuns: false });

    const [, init] = fetchMock.mock.calls[0];
    expect(JSON.parse(String(init?.body))).toMatchObject({
      action: 'app.bootstrap',
      include_runs: false
    });
  });

  it('sends workout.start as one atomic start request when a workout is supplied', async () => {
    const workout = { id: 'workout_1', name: 'Draft', blocks: [] };
    const fetchMock = vi.fn(async (_input: RequestInfo | URL, _init?: RequestInit) => jsonResponse({ workout, validation: { valid: true }, started_at: 'now' }));
    vi.stubGlobal('fetch', fetchMock);

    await startWorkout('workout_1', workout as never);

    const [, init] = fetchMock.mock.calls[0];
    expect(JSON.parse(String(init?.body))).toMatchObject({
      action: 'workout.start',
      workout_id: 'workout_1',
      workout
    });
  });

  it('opens local media at the containing Storage folder', () => {
    expect(storageNavigationParamsForMedia(localMedia)).toEqual({
      role: 'uploaded',
      folder_relative_path: 'workout'
    });
  });

  it('opens technical upload buckets at the visible Uploaded root', () => {
    expect(storageNavigationParamsForMedia({
      ...localMedia,
      workspace_relative_path: 'storage/uploaded/760a8ee7-de2a-4f93-8a5f-ccde8a9f503f/video.png',
      display_path: 'storage/uploaded/760a8ee7-de2a-4f93-8a5f-ccde8a9f503f/video.png'
    })).toEqual({
      role: 'uploaded',
      folder_relative_path: ''
    });
  });

  it('opens Drive media through its stable Storage file reference', () => {
    expect(storageNavigationParamsForMedia(driveMedia)).toEqual({
      file_id: 'file_drive',
      app_page: 'files/file_drive'
    });
  });

  it('opens Drive media at its source Drive folder when the folder is known', () => {
    expect(storageNavigationParamsForMedia(driveMedia, driveFolder)).toEqual({
      provider: 'google_drive',
      connection_id: 'drive_conn',
      drive_file_id: 'folder_drive',
      display_path: '/My Drive/workout'
    });
  });

  it('ignores stale Drive source folders that do not contain the media', () => {
    expect(storageNavigationParamsForMedia(driveMedia, { ...driveFolder, display_path: '/My Drive/other' })).toEqual({
      file_id: 'file_drive',
      app_page: 'files/file_drive'
    });
  });

  it('posts Storage navigation params through the shell', () => {
    const postMessage = vi.fn();
    vi.stubGlobal('window', {
      location: { origin: 'http://localhost', search: '' },
      parent: { postMessage }
    });

    openStorageForMedia(localMedia);

    expect(postMessage).toHaveBeenCalledWith(
      {
        type: 'maverick.widget.open-app',
        app_id: 'storage',
        params: {
          role: 'uploaded',
          folder_relative_path: 'workout'
        }
      },
      '*'
    );
  });

  it('posts source Drive folder navigation through the shell', () => {
    const postMessage = vi.fn();
    vi.stubGlobal('window', {
      location: { origin: 'http://localhost', search: '' },
      parent: { postMessage }
    });

    openStorageForMedia(driveMedia, driveFolder);

    expect(postMessage).toHaveBeenCalledWith(
      {
        type: 'maverick.widget.open-app',
        app_id: 'storage',
        params: {
          provider: 'google_drive',
          connection_id: 'drive_conn',
          drive_file_id: 'folder_drive',
          display_path: '/My Drive/workout'
        }
      },
      '*'
    );
  });

  it('opens Storage in Fitness Coach video picker mode', () => {
    expect(storageVideoPickerNavigationParamsForMedia(driveMedia, driveFolder)).toEqual({
      provider: 'google_drive',
      connection_id: 'drive_conn',
      drive_file_id: 'folder_drive',
      display_path: '/My Drive/workout',
      picker_accept: 'video',
      picker_mode: 'fitness-coach-media',
      picker_return_app_id: 'fitness-coach'
    });
  });

  it('posts video picker params through the shell', () => {
    const postMessage = vi.fn();
    vi.stubGlobal('window', {
      location: { origin: 'http://localhost', search: '' },
      parent: { postMessage }
    });

    openStorageVideoPicker(driveMedia, driveFolder);

    expect(postMessage).toHaveBeenCalledWith(
      {
        type: 'maverick.widget.open-app',
        app_id: 'storage',
        params: {
          provider: 'google_drive',
          connection_id: 'drive_conn',
          drive_file_id: 'folder_drive',
          display_path: '/My Drive/workout',
          picker_accept: 'video',
          picker_mode: 'fitness-coach-media',
          picker_return_app_id: 'fitness-coach'
        }
      },
      '*'
    );
  });

  it('converts Storage picker results into exercise media and source folder refs', () => {
    const selection = storageMediaSelectionFromPickerParams({
      picker_mode: 'fitness-coach-media',
      storage_picker_result: JSON.stringify({
        file: {
          id: 'file_drive',
          file_id: 'file_drive',
          provider: 'google_drive',
          connection_id: 'drive_conn',
          drive_file_id: 'drive_file',
          display_path: '/My Drive/workout/video.mp4',
          name: 'video.mp4',
          content_type: 'video/mp4',
          preview_kind: 'video',
          size_bytes: 42
        },
        source_display_path: '/My Drive/workout',
        source_folder: driveFolder
      })
    });

    expect(selection).toEqual({
      media: {
        kind: 'drive_file',
        provider: 'google_drive',
        stable_storage_file_id: 'file_drive',
        connection_id: 'drive_conn',
        drive_file_id: 'drive_file',
        display_path: '/My Drive/workout/video.mp4',
        name: 'video.mp4',
        content_type: 'video/mp4',
        preview_kind: 'video',
        size_bytes: 42,
        source_version: '',
        etag_or_version: '',
        capabilities: {}
      },
      sourceDisplayPath: '/My Drive/workout',
      sourceFolder: driveFolder
    });
  });

  it('rejects image picker results for the video-only flow', () => {
    expect(storageMediaSelectionFromPickerParams({
      picker_mode: 'fitness-coach-media',
      storage_picker_result: {
        file: {
          id: 'file_image',
          file_id: 'file_image',
          provider: 'local',
          workspace_relative_path: 'storage/uploaded/screenshot.png',
          display_path: 'storage/uploaded/screenshot.png',
          name: 'screenshot.png',
          content_type: 'image/png',
          preview_kind: 'image'
        }
      }
    })).toBeNull();
  });
});
