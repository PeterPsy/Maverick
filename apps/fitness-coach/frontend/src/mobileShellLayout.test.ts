import { readFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { describe, expect, it } from 'vitest';

const currentDir = dirname(fileURLToPath(import.meta.url));

function readSource(path: string) {
  return readFileSync(resolve(currentDir, path), 'utf8');
}

describe('mobile shell layout styles', () => {
  it('keeps the workspace surface behind the mobile shell header while offsetting scroll content', () => {
    const styles = readSource('styles.css');

    expect(styles).toMatch(/--fitness-shell-top-offset:\s*var\(--maverick-shell-mobile-content-top-offset,\s*0px\);/);
    expect(styles).toMatch(/--fitness-mobile-top-fade-height:\s*calc\(var\(--fitness-shell-top-offset\) \+ 1\.1rem\);/);
    expect(styles).toMatch(/\.fitness-app\s*{[\s\S]*padding:\s*0\.72rem 0\.8rem 0\.8rem;/);
    expect(styles).toMatch(/\.editor,\s*\.library\s*{[\s\S]*padding:\s*var\(--fitness-editor-top-clearance\) 0\.1rem var\(--fitness-editor-bottom-clearance\);/);
    expect(styles).toMatch(/@media \(max-width: 920px\)[\s\S]*\.setup-panel::before\s*{[\s\S]*height:\s*var\(--fitness-mobile-top-fade-height\);[\s\S]*pointer-events:\s*none;[\s\S]*background:\s*linear-gradient\(/);
    expect(styles).toMatch(/@media \(max-width: 920px\)[\s\S]*\.editor,\s*\.library,\s*\.fitness-main-skeleton\s*{[\s\S]*--fitness-editor-top-clearance:\s*calc\(0\.7rem \+ var\(--fitness-shell-top-offset\)\);/);
    expect(styles).not.toContain('padding: calc(0.72rem + var(--maverick-shell-mobile-content-top-offset, 0px))');
  });
});
