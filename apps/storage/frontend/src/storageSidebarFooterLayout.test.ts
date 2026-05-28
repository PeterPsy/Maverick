import { readFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { describe, expect, it } from 'vitest';

const currentDir = dirname(fileURLToPath(import.meta.url));

function readSource(path: string) {
  return readFileSync(resolve(currentDir, path), 'utf8');
}

describe('storage sidebar footer layout', () => {
  it('keeps the Drive connection button in the same footer row as folder and upload actions', () => {
    const styles = readSource('styles/sidebar-widget.css');
    const footerActionsStart = styles.indexOf('.storage-sidebar-footer-actions {');
    const footerActionsEnd = styles.indexOf('.storage-sidebar-footer-actions.is-naming');
    expect(footerActionsStart).toBeGreaterThanOrEqual(0);
    expect(footerActionsEnd).toBeGreaterThan(footerActionsStart);

    const footerActionsStyles = styles.slice(footerActionsStart, footerActionsEnd);
    expect(footerActionsStyles).toContain('grid-template-columns: minmax(0, 1fr) 2.65rem 2.65rem;');

    const footerSource = readSource('widgets/storage-sidebar-footer/main.tsx');
    expect(footerSource).toContain("aria-label={isConnectingDrive ? 'Connecting Google Drive' : 'Connect Drive'}");
  });
});
