import { readFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { describe, expect, it } from 'vitest';

const currentDir = dirname(fileURLToPath(import.meta.url));

function readSource(path: string) {
  return readFileSync(resolve(currentDir, path), 'utf8');
}

describe('storage Drive load more', () => {
  it('continues Drive pagination through Drive list actions instead of the local catalog', () => {
    const source = readSource('main.tsx');
    const loadMoreStart = source.indexOf('async function loadMoreFiles()');
    const loadMoreEnd = source.indexOf('async function syncViewFilter()');
    expect(loadMoreStart).toBeGreaterThanOrEqual(0);
    expect(loadMoreEnd).toBeGreaterThan(loadMoreStart);
    const loadMoreBody = source.slice(loadMoreStart, loadMoreEnd);
    const driveBranchStart = loadMoreBody.indexOf('if (driveTarget) {');
    const localCatalogStart = loadMoreBody.indexOf('const payload = await loadCatalog');
    expect(driveBranchStart).toBeGreaterThanOrEqual(0);
    expect(localCatalogStart).toBeGreaterThan(driveBranchStart);
    const driveBranch = loadMoreBody.slice(driveBranchStart, localCatalogStart);

    expect(driveBranch).toContain("const pageToken = catalogPagination.next_page_token || '';");
    expect(driveBranch).toContain('listDriveChildren(driveTarget.connectionId, driveTarget.driveFileId, { limit: DRIVE_PAGE_LIMIT, pageToken, signal: driveAbortController.signal })');
    expect(driveBranch).toContain('listDriveRoots(driveTarget.connectionId, { limit: DRIVE_PAGE_LIMIT, pageToken, signal: driveAbortController.signal })');
    expect(driveBranch).not.toContain('nextLimit');
    expect(driveBranch).toContain('return;');
    expect(driveBranch).not.toContain('loadCatalog');
  });
});
