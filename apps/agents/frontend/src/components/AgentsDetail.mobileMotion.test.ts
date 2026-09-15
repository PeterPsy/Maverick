import { readFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { describe, expect, it } from 'vitest';

const currentDir = dirname(fileURLToPath(import.meta.url));

describe('agent type detail layout', () => {
  it('contains only the self-contained agent editor', () => {
    const source = readFileSync(resolve(currentDir, 'AgentsDetail.tsx'), 'utf8');

    expect(source).toContain('Explicit Skills');
    expect(source).toContain('Instructions');
    expect(source).not.toContain('Trace');
    expect(source).not.toContain('Role');
    expect(source).not.toContain('Prompt Preview');
  });

  it('creates agents with an empty explicit skill selection', () => {
    const source = readFileSync(resolve(currentDir, 'NewAgentModal.tsx'), 'utf8');

    expect(source).toContain("setSelectedSkillIds([])");
    expect(source).toContain('Instructions');
    expect(source).not.toContain('role prompt');
    expect(source).not.toContain('default skills');
  });
});
