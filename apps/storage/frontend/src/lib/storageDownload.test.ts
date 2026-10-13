// @vitest-environment happy-dom
import { afterEach, expect, it, vi } from 'vitest';
import { downloadStorageBlob, startStorageDownload } from './storageDownload';

afterEach(() => { vi.restoreAllMocks(); vi.useRealTimers(); });

it('dispatches a download from an attached anchor in the authenticated frame', () => {
  const clicked = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(function (this: HTMLAnchorElement) {
    expect(this.isConnected).toBe(true);
    expect(this.getAttribute('href')).toBe('/api/apps/storage/media?download=1');
    expect(this.download).toBe('image.png');
    expect(this.target).toBe('');
  });
  startStorageDownload('/api/apps/storage/media?download=1', 'image.png');
  expect(clicked).toHaveBeenCalledOnce();
  expect(document.querySelector('a[download]')).toBeNull();
});

it('keeps exported blob bytes available during asynchronous WebKit handoff', () => {
  vi.useFakeTimers();
  vi.spyOn(URL, 'createObjectURL').mockReturnValue('blob:export');
  const revoke = vi.spyOn(URL, 'revokeObjectURL').mockImplementation(() => {});
  vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {});
  downloadStorageBlob(new Blob(['Export']), 'export.txt');
  expect(revoke).not.toHaveBeenCalled();
  vi.advanceTimersByTime(60_000);
  expect(revoke).toHaveBeenCalledWith('blob:export');
});
