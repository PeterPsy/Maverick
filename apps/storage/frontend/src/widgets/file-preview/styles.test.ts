import { readFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { describe, expect, it } from 'vitest';

const currentDir = dirname(fileURLToPath(import.meta.url));

function readStyle(filename: string): string {
  return readFileSync(resolve(currentDir, filename), 'utf8');
}

describe('storage file preview widget styles', () => {
  it('uses neutral chat-style chrome instead of red gradient accents', () => {
    const styles = readStyle('styles.css');

    expect(styles).not.toMatch(/gradient/i);
    expect(styles).not.toContain('#d72451');
    expect(styles).not.toContain('#f84b78');
    expect(styles).not.toContain('215, 36, 81');
  });

  it('keeps the document surface tall enough for previews', () => {
    const styles = readStyle('styles.css');
    const source = readStyle('main.tsx');

    expect(styles).toContain('min-height: 20rem;');
    expect(source).toContain('const WIDGET_MAX_HEIGHT_PX = 520;');
  });

  it('keeps iframe scrolling hidden and exposes a transient document scrollbar', () => {
    const styles = readStyle('styles.css');

    expect(styles).toMatch(/html,[\s\S]*body,[\s\S]*#storage-file-preview-root\s*{[\s\S]*overflow:\s*hidden;/);
    expect(styles).toContain('scrollbar-width: none;');
    expect(styles).toContain('.file-widget__document.is-scrolling');
    expect(styles).toContain('.file-widget__document.is-scrolling::-webkit-scrollbar-thumb');
  });

  it('keeps open-in-storage on the title and groups header action buttons', () => {
    const source = readStyle('main.tsx');
    const styles = readStyle('styles.css');

    expect(source).toContain('className="file-widget__bar"');
    expect(source).toContain('className="file-widget__title-button"');
    expect(source).toContain('className="file-widget__actions"');
    expect(source).toContain('className="file-widget__action file-widget__open"');
    expect(styles).toContain('text-decoration: underline;');
    expect(styles).toContain('.file-widget__actions');
    expect(source).not.toContain('role="button"');
    expect(source).not.toContain('handleDocumentClick');
  });

  it('exposes fullscreen chrome for embedded previews and square mobile layout', () => {
    const source = readStyle('main.tsx');
    const styles = readStyle('styles.css');

    expect(source).toContain('requestElementFullscreen(root)');
    expect(source).toContain("fullscreenActive ? 'fullscreen_exit' : 'fullscreen'");
    expect(styles).toContain('.file-widget.is-fullscreen');
    expect(styles).toContain('@media (max-width: 780px)');
    expect(styles).toMatch(/@media \(max-width: 780px\)[\s\S]*\.file-widget\s*{[\s\S]*border-radius:\s*0;/);
    expect(styles).toMatch(/@media \(max-width: 780px\)[\s\S]*\.file-widget__bar h3\s*{[\s\S]*overflow-wrap:\s*anywhere;[\s\S]*white-space:\s*normal;/);
    expect(styles).toMatch(/@media \(max-width: 780px\)[\s\S]*\.file-widget__title-button\s*{[\s\S]*text-overflow:\s*clip;[\s\S]*white-space:\s*normal;/);
  });

  it('keeps the skeleton visible until inline preview content is ready', () => {
    const source = readStyle('main.tsx');
    const styles = readStyle('styles.css');

    expect(source).toContain('file-widget--skeleton');
    expect(source).toContain('file-widget__skeleton-body');
    expect(source).toContain('setPreviewLoading(canInlinePreview(result.file))');
    expect(source).toContain('if (!file || previewLoading)');
    expect(source).toContain('await blob.text()');
    expect(source).not.toContain('Loading preview...');
    expect(source).not.toContain('Loading file preview...');
    expect(styles).toContain('@keyframes file-widget-skeleton-pulse');
  });
});
