import { readFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { describe, expect, it } from 'vitest';

const currentDir = dirname(fileURLToPath(import.meta.url));

function readSource(path: string) {
  return readFileSync(resolve(currentDir, path), 'utf8');
}

describe('storage Drive upload wiring', () => {
  it('uploads dropped files through drive_write when the active view is a Drive folder', () => {
    const source = readSource('main.tsx');
    const uploadStart = source.indexOf('async function uploadSelectedFiles(selectedFiles: File[])');
    const uploadEnd = source.indexOf('function handleAppDragEnter');
    expect(uploadStart).toBeGreaterThanOrEqual(0);
    expect(uploadEnd).toBeGreaterThan(uploadStart);
    const uploadBody = source.slice(uploadStart, uploadEnd);

    expect(uploadBody).toContain('const driveUploadTarget = driveTargetRef.current;');
    expect(uploadBody).toContain("if (!driveUploadTarget?.driveFileId) {");
    expect(uploadBody).toContain('const payload = await uploadDriveFile(file, driveUploadTarget);');
    expect(uploadBody).toContain("setDropMessage(`Uploaded ${selectedFiles.length === 1 ? selectedFiles[0].name : `${selectedFiles.length} files`} to ${driveUploadTargetLabel(driveUploadTarget)}`);");
    expect(uploadBody).not.toContain('Google Drive upload is not supported here yet.');
  });

  it('lets the sidebar footer upload to Drive while keeping folder creation local', () => {
    const source = readSource('widgets/storage-sidebar-footer/main.tsx');

    expect(source).toContain("type DriveFolderActionTarget = {");
    expect(source).toContain("provider: 'google_drive';");
    expect(source).toContain("const createDisabled = !target || isDriveTarget(target) || isCreatingFolder || isUploading;");
    expect(source).toContain("const uploadDisabled = !target || (isDriveTarget(target) && !target.driveFileId) || isCreatingFolder || isUploading;");
    expect(source).toContain('await uploadDriveFile(file, nextTarget, uploadOptions)');
  });
});
