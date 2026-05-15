import { readFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { describe, expect, it } from 'vitest';

const currentDir = dirname(fileURLToPath(import.meta.url));

function readStyle(filename: string) {
  return readFileSync(resolve(currentDir, filename), 'utf8');
}

describe('agents app scrollbars', () => {
  it('hides the general app scrollbars without disabling content scroll', () => {
    const baseStyles = readStyle('base.css');
    const detailStyles = readStyle('detail.css');

    expect(baseStyles).toMatch(/body\s*\{[^}]*scrollbar-width: none;/);
    expect(baseStyles).toContain('body::-webkit-scrollbar');
    expect(detailStyles).toMatch(/\.agents-detail\s*\{[^}]*overflow: auto;[^}]*scrollbar-width: none;/);
    expect(detailStyles).toContain('.agents-detail::-webkit-scrollbar');
  });

  it('uses reveal-on-interaction scrollbars for common prompt, skills, and preview panels', () => {
    const panelStyles = readStyle('panel-scrollbars.css');

    expect(panelStyles).toMatch(
      /\.bento-card-common textarea,\s*\.agent-skill-picker,\s*\.prompt-review-band pre\s*\{[^}]*scrollbar-color: transparent transparent;/
    );
    expect(panelStyles).toMatch(
      /\.bento-card-common:hover textarea,\s*\.bento-card-common:focus-within textarea,[\s\S]*\.prompt-review-band pre:focus\s*\{[^}]*scrollbar-color: rgba\(255, 255, 255, 0\.42\) transparent;/
    );
    expect(panelStyles).toContain('.bento-card-skills:hover .agent-skill-picker::-webkit-scrollbar-thumb');
    expect(panelStyles).toContain('.prompt-review-band:hover pre::-webkit-scrollbar-thumb');
    expect(panelStyles).toContain('background-color: rgba(255, 255, 255, 0.42);');
  });

  it('centers skill row title and subtitle as one block inside the skills panel', () => {
    const panelStyles = readStyle('panel-scrollbars.css');

    expect(panelStyles).toMatch(/\.agent-skill-picker \.skill-choice\s*\{[^}]*align-items: center;/);
    expect(panelStyles).toMatch(/\.agent-skill-picker \.skill-choice span\s*\{[^}]*align-content: center;[^}]*align-self: center;/);
    expect(panelStyles).toMatch(/\.agent-skill-picker \.skill-choice strong,\s*\.agent-skill-picker \.skill-choice small\s*\{[^}]*line-height: 1\.15;/);
  });
});
