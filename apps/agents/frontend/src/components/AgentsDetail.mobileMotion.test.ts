import { readFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { describe, expect, it } from 'vitest';

const currentDir = dirname(fileURLToPath(import.meta.url));

describe('agent type detail layout', () => {
  it('keeps trace below role and removes the prompt signal animation', () => {
    const source = readFileSync(resolve(currentDir, 'AgentsDetail.tsx'), 'utf8');

    expect(source).toContain('className="bento-card bento-card-trace"');
    expect(source).not.toContain('function PromptSignal');
    expect(source).not.toContain('prompt-signal');
    expect(source).not.toContain('rotate: 360');
  });
});
