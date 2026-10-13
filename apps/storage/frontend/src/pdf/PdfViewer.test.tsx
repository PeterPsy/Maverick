// @vitest-environment happy-dom
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { getDocument } from 'pdfjs-dist';
import PdfViewer from './PdfViewer';

vi.mock('pdfjs-dist', () => ({ getDocument: vi.fn(), GlobalWorkerOptions: {} }));

let container: HTMLDivElement;
let root: Root;
let destroy: ReturnType<typeof vi.fn>;
let cancel: ReturnType<typeof vi.fn>;
let getPage: ReturnType<typeof vi.fn>;

beforeEach(() => {
  (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
  vi.stubGlobal('ResizeObserver', class { observe() {} disconnect() {} });
  vi.spyOn(HTMLElement.prototype, 'clientWidth', 'get').mockReturnValue(344);
  vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockReturnValue({} as CanvasRenderingContext2D);
  destroy = vi.fn().mockResolvedValue(undefined);
  cancel = vi.fn();
  getPage = vi.fn().mockResolvedValue({
    getViewport: ({ scale }: { scale: number }) => ({ width: 600 * scale, height: 800 * scale }),
    render: () => ({ promise: Promise.resolve(), cancel }),
  });
  vi.mocked(getDocument).mockReturnValue({
    promise: Promise.resolve({ numPages: 3, getPage }), destroy,
  } as unknown as ReturnType<typeof getDocument>);
  container = document.createElement('div');
  document.body.append(container);
  root = createRoot(container);
});

afterEach(async () => {
  await act(async () => root.unmount());
  container.remove();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

async function mount(url = '/media/report.pdf') {
  await act(async () => root.render(<PdfViewer key={url} previewUrl={url} fileName="Report.pdf" />));
}

async function click(label: string) {
  const button = container.querySelector<HTMLButtonElement>(`button[aria-label="${label}"]`)!;
  await act(async () => button.click());
}

it('loads authenticated PDF pages, navigates, zooms and resets when the file changes', async () => {
  await mount();
  expect(getDocument).toHaveBeenCalledWith({ url: '/media/report.pdf', withCredentials: true });
  expect(container.querySelector<HTMLButtonElement>('[aria-label="Previous page"]')?.disabled).toBe(true);
  expect(container.querySelector('canvas')?.getAttribute('aria-label')).toBe('PDF page 1');
  expect(container.querySelector('canvas')?.style.width).toBe('320px');
  await click('Next page');
  expect(getPage).toHaveBeenLastCalledWith(2);
  await click('Next page');
  expect(container.querySelector<HTMLButtonElement>('[aria-label="Next page"]')?.disabled).toBe(true);
  await click('Previous page');
  expect(getPage).toHaveBeenLastCalledWith(2);
  await click('Zoom in');
  expect(container.querySelector('canvas')?.style.width).toBe('400px');
  await click('Fit PDF to width');
  expect(container.querySelector('canvas')?.style.width).toBe('320px');
  await mount('/media/another.pdf');
  expect(destroy).toHaveBeenCalled();
  expect(getPage).toHaveBeenLastCalledWith(1);
});

it('cancels an in-flight render and destroys the document when closed', async () => {
  getPage.mockResolvedValue({
    getViewport: () => ({ width: 320, height: 440 }),
    render: () => ({ promise: new Promise(() => {}), cancel }),
  });
  await mount();
  await act(async () => root.render(null));
  expect(cancel).toHaveBeenCalled();
  expect(destroy).toHaveBeenCalled();
});

it('reports a broken PDF and page errors without leaving a blank preview', async () => {
  vi.mocked(getDocument).mockReturnValue({ promise: Promise.reject(new Error('Invalid PDF')), destroy } as unknown as ReturnType<typeof getDocument>);
  await mount();
  expect(container.querySelector('[role="alert"]')?.textContent).toContain('Invalid PDF');
  vi.mocked(getDocument).mockReturnValue({ promise: Promise.resolve({ numPages: 1,
    getPage: vi.fn().mockRejectedValue(new Error('Page unavailable')) }), destroy } as unknown as ReturnType<typeof getDocument>);
  await mount('/media/broken-page.pdf');
  expect(container.querySelector('[role="alert"]')?.textContent).toContain('Page unavailable');
});

it('explains password-protected files and releases the pending loading task', async () => {
  const task = { promise: new Promise(() => {}), destroy, onPassword: undefined } as unknown as ReturnType<typeof getDocument>;
  vi.mocked(getDocument).mockReturnValue(task);
  await mount();
  await act(async () => task.onPassword?.(() => {}, 1));
  expect(container.querySelector('[role="alert"]')?.textContent).toContain('requires a password');
  expect(destroy).toHaveBeenCalled();
});
