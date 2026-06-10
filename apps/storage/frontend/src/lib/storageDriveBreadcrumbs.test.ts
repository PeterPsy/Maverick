import { describe, expect, it } from 'vitest';
import {
  driveBreadcrumbItems,
  driveBreadcrumbTargetsFromInput,
  driveBreadcrumbTrailForFolder,
  driveBreadcrumbTrailForTarget,
  type DriveBreadcrumbTarget,
} from './storageDriveBreadcrumbs';
import type { StorageFolder } from '../types';

function driveFolder(overrides: Partial<StorageFolder> = {}): StorageFolder {
  return {
    connection_id: 'drive_conn_1',
    display_path: '/My Drive',
    drive_file_id: 'root',
    id: 'folder_root',
    modified_at: '',
    name: 'My Drive',
    provider: 'google_drive',
    relative_path: '',
    role: '',
    workspace_relative_path: '',
    ...overrides,
  };
}

describe('Storage Drive breadcrumbs', () => {
  it('keeps Drive folder identities while navigating down the tree', () => {
    let trail: DriveBreadcrumbTarget[] = [];
    trail = driveBreadcrumbTrailForFolder(driveFolder(), trail);
    trail = driveBreadcrumbTrailForFolder(driveFolder({
      display_path: '/My Drive/Clients',
      drive_file_id: 'folder_clients',
      id: 'folder_clients_stable',
      name: 'Clients',
    }), trail);
    trail = driveBreadcrumbTrailForFolder(driveFolder({
      display_path: '/My Drive/Clients/Reports',
      drive_file_id: 'folder_reports',
      id: 'folder_reports_stable',
      name: 'Reports',
    }), trail);

    expect(driveBreadcrumbItems('/My Drive/Clients/Reports', trail)).toEqual([
      {
        connectionId: 'drive_conn_1',
        displayPath: '/My Drive',
        driveFileId: 'root',
        label: 'My Drive',
        path: '/My Drive',
      },
      {
        connectionId: 'drive_conn_1',
        displayPath: '/My Drive/Clients',
        driveFileId: 'folder_clients',
        label: 'Clients',
        path: '/My Drive/Clients',
      },
      {
        connectionId: 'drive_conn_1',
        displayPath: '/My Drive/Clients/Reports',
        driveFileId: 'folder_reports',
        label: 'Reports',
        path: '/My Drive/Clients/Reports',
      },
    ]);
  });

  it('canonicalizes localized My Drive labels without losing middle folder ids', () => {
    const trail: DriveBreadcrumbTarget[] = [
      {
        connectionId: 'drive_conn_1',
        displayPath: '/My Drive',
        driveFileId: 'root',
        label: 'My Drive',
        path: '/My Drive',
      },
      {
        connectionId: 'drive_conn_1',
        displayPath: '/My Drive/fitness-coach',
        driveFileId: 'folder_fitness',
        label: 'fitness-coach',
        path: '/My Drive/fitness-coach',
      },
      {
        connectionId: 'drive_conn_1',
        displayPath: '/My Drive/fitness-coach/Mobility',
        driveFileId: 'folder_mobility',
        label: 'Mobility',
        path: '/My Drive/fitness-coach/Mobility',
      },
    ];

    expect(driveBreadcrumbItems('/Il mio Drive/fitness-coach/Mobility', trail)).toEqual([
      {
        connectionId: 'drive_conn_1',
        displayPath: '/My Drive',
        driveFileId: 'root',
        label: 'My Drive',
        path: '/My Drive',
      },
      {
        connectionId: 'drive_conn_1',
        displayPath: '/My Drive/fitness-coach',
        driveFileId: 'folder_fitness',
        label: 'fitness-coach',
        path: '/My Drive/fitness-coach',
      },
      {
        connectionId: 'drive_conn_1',
        displayPath: '/My Drive/fitness-coach/Mobility',
        driveFileId: 'folder_mobility',
        label: 'Mobility',
        path: '/My Drive/fitness-coach/Mobility',
      },
    ]);
  });

  it('normalizes Drive breadcrumb targets from backend payloads', () => {
    expect(driveBreadcrumbTargetsFromInput([
      {
        connection_id: 'drive_conn_1',
        display_path: '/Il mio Drive',
        drive_file_id: 'root',
        label: 'Il mio Drive',
      },
      {
        connection_id: 'drive_conn_1',
        display_path: '/My Drive/fitness-coach',
        drive_file_id: 'folder_fitness',
        label: 'fitness-coach',
      },
      {
        connection_id: 'other_conn',
        display_path: '/My Drive/ignored',
        drive_file_id: 'folder_ignored',
        label: 'ignored',
      },
    ], 'drive_conn_1')).toEqual([
      {
        connectionId: 'drive_conn_1',
        displayPath: '/My Drive',
        driveFileId: 'root',
        label: 'My Drive',
        path: '/My Drive',
      },
      {
        connectionId: 'drive_conn_1',
        displayPath: '/My Drive/fitness-coach',
        driveFileId: 'folder_fitness',
        label: 'fitness-coach',
        path: '/My Drive/fitness-coach',
      },
    ]);
  });

  it('truncates the trail when a Drive breadcrumb target is selected', () => {
    const trail: DriveBreadcrumbTarget[] = [
      {
        connectionId: 'drive_conn_1',
        displayPath: '/My Drive',
        driveFileId: 'root',
        label: 'My Drive',
        path: '/My Drive',
      },
      {
        connectionId: 'drive_conn_1',
        displayPath: '/My Drive/Clients',
        driveFileId: 'folder_clients',
        label: 'Clients',
        path: '/My Drive/Clients',
      },
      {
        connectionId: 'drive_conn_1',
        displayPath: '/My Drive/Clients/Reports',
        driveFileId: 'folder_reports',
        label: 'Reports',
        path: '/My Drive/Clients/Reports',
      },
    ];

    expect(driveBreadcrumbTrailForTarget({
      connectionId: 'drive_conn_1',
      displayPath: '/My Drive/Clients',
      driveFileId: 'folder_clients',
    }, trail)).toEqual(trail.slice(0, 2));
  });

  it('infers the root id for direct Drive folder navigation and leaves unknown middle folders inert', () => {
    const trail = driveBreadcrumbTrailForTarget({
      connectionId: 'drive_conn_1',
      displayPath: '/My Drive/Clients/Reports',
      driveFileId: 'folder_reports',
    }, []);

    expect(driveBreadcrumbItems('/My Drive/Clients/Reports', trail)).toEqual([
      {
        connectionId: 'drive_conn_1',
        displayPath: '/My Drive',
        driveFileId: 'root',
        label: 'My Drive',
        path: '/My Drive',
      },
      {
        displayPath: '/My Drive/Clients',
        label: 'Clients',
        path: '/My Drive/Clients',
      },
      {
        connectionId: 'drive_conn_1',
        displayPath: '/My Drive/Clients/Reports',
        driveFileId: 'folder_reports',
        label: 'Reports',
        path: '/My Drive/Clients/Reports',
      },
    ]);
  });
});
