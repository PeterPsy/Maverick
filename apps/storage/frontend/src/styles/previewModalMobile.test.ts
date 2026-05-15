import { readFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { describe, expect, it } from 'vitest';

const currentDir = dirname(fileURLToPath(import.meta.url));
const frontendSrcRoot = resolve(currentDir, '..');

function readSource(path: string) {
  return readFileSync(resolve(frontendSrcRoot, path), 'utf8');
}

describe('storage preview modal mobile styles', () => {
  it('starts below the mobile shell header and keeps compact controls usable', () => {
    const styles = readSource('styles/main.css');
    const source = readSource('main.tsx');

    expect(source).toContain('previewViewportSize.width > 780');
    expect(source).toContain('icon-button preview-fullscreen-action');
    expect(styles).toMatch(/\.storage-shell\s*{[\s\S]*--storage-shell-top-offset:\s*var\(--maverick-shell-mobile-content-top-offset,\s*0px\);/);
    expect(styles).toMatch(/@media \(max-width: 780px\)[\s\S]*\.preview-modal-backdrop\s*{[\s\S]*inset:\s*var\(--storage-shell-top-offset\) 0 0 0;[\s\S]*padding:\s*0;/);
    expect(styles).toMatch(/@media \(max-width: 780px\)[\s\S]*\.preview-modal\s*{[\s\S]*width:\s*100vw;[\s\S]*height:\s*100%;[\s\S]*border:\s*0;[\s\S]*border-radius:\s*0;/);
    expect(styles).toMatch(/@media \(max-width: 780px\)[\s\S]*\.preview-modal-header\s*{[\s\S]*align-items:\s*center;[\s\S]*padding:\s*0 max\(10px,\s*env\(safe-area-inset-right\)\) 0 max\(12px,\s*env\(safe-area-inset-left\)\);/);
    expect(styles).toMatch(/@media \(max-width: 780px\)[\s\S]*\.preview-modal-actions\s*{[\s\S]*flex-wrap:\s*nowrap;/);
    expect(styles).toMatch(/@media \(max-width: 780px\)[\s\S]*\.preview-modal-actions \.preview-fullscreen-action\s*{[\s\S]*display:\s*none;/);
    expect(styles).toMatch(/@media \(max-width: 780px\)[\s\S]*\.preview-modal-header h2\s*{[\s\S]*overflow:\s*hidden;[\s\S]*text-overflow:\s*ellipsis;[\s\S]*white-space:\s*nowrap;/);
    expect(styles).toMatch(/@media \(max-width: 780px\)[\s\S]*\.preview-modal-body > img\s*{[\s\S]*width:\s*100%;[\s\S]*height:\s*100%;[\s\S]*object-fit:\s*contain;/);
    expect(styles).toMatch(/@media \(max-width: 780px\)[\s\S]*\.preview-modal-header \.storage-eyebrow\s*{[\s\S]*display:\s*none;/);
  });
});
