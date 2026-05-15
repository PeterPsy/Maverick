import { describe, expect, it, vi } from 'vitest';
import { canRequestFullscreen, currentFullscreenElement, elementIsFullscreen, exitDocumentFullscreen, requestElementFullscreen } from './browserFullscreen';

function documentLike(value: object) {
  return value as unknown as Document;
}

describe('browser fullscreen helpers', () => {
  it('detects standard and prefixed fullscreen elements', () => {
    const element = {} as Element;
    expect(currentFullscreenElement(documentLike({ fullscreenElement: element }))).toBe(element);
    expect(currentFullscreenElement(documentLike({ webkitFullscreenElement: element }))).toBe(element);
    expect(currentFullscreenElement(documentLike({ msFullscreenElement: element }))).toBe(element);
  });

  it('requires a request function and an enabled document', () => {
    const element = { requestFullscreen: vi.fn() } as unknown as HTMLElement;
    expect(canRequestFullscreen(element, documentLike({ fullscreenEnabled: true }))).toBe(true);
    expect(canRequestFullscreen(element, documentLike({ fullscreenEnabled: false }))).toBe(false);
    expect(canRequestFullscreen({} as HTMLElement, documentLike({ fullscreenEnabled: true }))).toBe(false);
  });

  it('compares the active fullscreen element', () => {
    const element = {} as HTMLElement;
    expect(elementIsFullscreen(element, documentLike({ fullscreenElement: element }))).toBe(true);
    expect(elementIsFullscreen(element, documentLike({ fullscreenElement: {} as Element }))).toBe(false);
  });

  it('requests and exits fullscreen through available browser methods', async () => {
    const requestFullscreen = vi.fn();
    const exitFullscreen = vi.fn();

    await requestElementFullscreen({ requestFullscreen } as unknown as HTMLElement);
    await exitDocumentFullscreen(documentLike({ exitFullscreen }));

    expect(requestFullscreen).toHaveBeenCalledTimes(1);
    expect(exitFullscreen).toHaveBeenCalledTimes(1);
  });
});
