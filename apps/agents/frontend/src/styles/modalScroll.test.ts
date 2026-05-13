import { readFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { describe, expect, it } from 'vitest';

const currentDir = dirname(fileURLToPath(import.meta.url));

function readModalStyles() {
  return readFileSync(resolve(currentDir, 'modal.css'), 'utf8');
}

describe('agents modal scroll layout', () => {
  it('uses the base background token and keeps the normal viewport scroll on skills only', () => {
    const styles = readModalStyles();

    expect(styles).toMatch(/\.agent-modal\s*\{[^}]*background: var\(--maverick-bg\);/);
    expect(styles).not.toMatch(/\.agent-modal\s*\{[^}]*background: var\(--maverick-bg-strong\);/);
    expect(styles).toMatch(/\.modal-body\s*\{[^}]*overflow: visible;/);
    expect(styles).toMatch(/\.modal-skill-picker\s*\{[^}]*overflow-y: auto;/);
    expect(styles).toContain('@media (max-height: 700px)');
  });

  it('switches low viewports to whole-modal scrolling', () => {
    const styles = readModalStyles();

    expect(styles).toMatch(/@media \(max-height: 700px\) \{[\s\S]*\.agent-modal\s*\{[^}]*overflow-y: auto;[^}]*\}/);
    expect(styles).toMatch(
      /@media \(max-height: 700px\) \{[\s\S]*\.modal-skill-picker\s*\{[^}]*max-height: none;[^}]*overflow: visible;[^}]*\}/
    );
  });
});
