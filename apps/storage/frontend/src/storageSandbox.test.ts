import { readdirSync, readFileSync, statSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { describe, expect, it } from 'vitest';

const sourceRoot = path.dirname(fileURLToPath(import.meta.url));
const modalCallPattern = /\b(?:window\.)?confirm\s*\(/;

function frontendSourceFiles(directory: string): string[] {
  return readdirSync(directory)
    .flatMap((entry) => {
      const fullPath = path.join(directory, entry);
      const stats = statSync(fullPath);
      if (stats.isDirectory()) return frontendSourceFiles(fullPath);
      return /\.(ts|tsx)$/.test(entry) ? [fullPath] : [];
    });
}

describe('storage sandbox compatibility', () => {
  it('does not call native confirm dialogs from frontend source', () => {
    const offenders = frontendSourceFiles(sourceRoot).filter((filePath) => {
      return modalCallPattern.test(readFileSync(filePath, 'utf8'));
    });

    expect(offenders.map((filePath) => path.relative(sourceRoot, filePath))).toEqual([]);
  });
});
