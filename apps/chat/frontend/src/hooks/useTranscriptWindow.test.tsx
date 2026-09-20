/** @vitest-environment happy-dom */
import { act, useRef, useState } from 'react';
import { createRoot } from 'react-dom/client';
import { expect, it, vi } from 'vitest';
import type { ChatMessage } from '../api/client';
import { useTranscriptWindow } from './useTranscriptWindow';

it('keeps 5000 accessible messages in a bounded DOM window while scrolling both directions', async () => {
  vi.useFakeTimers();
  const messages: ChatMessage[] = Array.from({ length: 5000 }, (_, index) => ({
    id: String(index), role: 'system', content: `Message ${index}`, createdAt: '', status: 'complete',
  }));
  let setSpeaking: (id: string | null) => void = () => {};
  function Harness() {
    const viewport = useRef<HTMLDivElement | null>(null);
    const [speaking, updateSpeaking] = useState<string | null>(null);
    setSpeaking = updateSpeaking;
    const view = useTranscriptWindow(messages, viewport, speaking);
    return <div ref={viewport} data-viewport><div ref={view.container} data-window>
      <div style={{ height: view.before }} />
      {view.rows.map(message => <div data-row={message.id} key={message.id} hidden={view.hiddenRowId === message.id}>{message.content}</div>)}
      <div style={{ height: view.after }} />
    </div></div>;
  }
  const boundingRect = vi.spyOn(HTMLElement.prototype, 'getBoundingClientRect').mockImplementation(function(this: HTMLElement) {
    const top = this.hasAttribute('data-window') ? -(this.parentElement?.scrollTop || 0) : 0;
    return { top, bottom: top + 600, left: 0, right: 800, width: 800, height: 600, x: 0, y: top, toJSON: () => ({}) };
  });
  const container = document.createElement('div');
  document.body.append(container);
  const root = createRoot(container);
  try {
    await act(async () => { root.render(<Harness />); });
    await act(async () => { vi.advanceTimersByTime(20); });
    const viewport = container.querySelector('[data-viewport]') as HTMLElement;
    expect(container.querySelectorAll('[data-row]').length).toBeLessThan(30);
    expect(container.textContent).toContain('Message 0');
    const speakingRow = container.querySelector('[data-row="0"]')!;
    await act(async () => { setSpeaking('0'); });
    await act(async () => { viewport.scrollTop = 450000; viewport.dispatchEvent(new Event('scroll')); vi.advanceTimersByTime(20); });
    expect(container.querySelector('[data-row="0"]')).toBe(speakingRow);
    expect((speakingRow as HTMLElement).hidden).toBe(true);
    expect(container.querySelectorAll('[data-row]').length).toBeLessThan(31);
    await act(async () => { setSpeaking(null); });
    expect(container.querySelector('[data-row="0"]')).toBeNull();
    await act(async () => { viewport.scrollTop = 450000; viewport.dispatchEvent(new Event('scroll')); vi.advanceTimersByTime(20); });
    expect(container.textContent).toContain('Message 2500');
    expect(container.textContent).not.toContain('Message 0');
    expect(container.querySelectorAll('[data-row]').length).toBeLessThan(30);
    await act(async () => { viewport.scrollTop = 899400; viewport.dispatchEvent(new Event('scroll')); vi.advanceTimersByTime(20); });
    expect(container.textContent).toContain('Message 4999');
    await act(async () => { viewport.scrollTop = 0; viewport.dispatchEvent(new Event('scroll')); vi.advanceTimersByTime(20); });
    expect(container.textContent).toContain('Message 0');
  } finally {
    await act(async () => root.unmount());
    container.remove();
    boundingRect.mockRestore();
    vi.useRealTimers();
  }
});

it('keeps the bottom and the visible reading position stable when measured rows grow', async () => {
  vi.useFakeTimers();
  const messages: ChatMessage[] = Array.from({ length: 200 }, (_, index) => ({
    id: String(index), role: 'system', content: `Message ${index}`, createdAt: '', status: 'complete',
  }));
  const heights = new Map<string, number>();
  let resize: ResizeObserverCallback | undefined;
  vi.stubGlobal('ResizeObserver', class {
    constructor(callback: ResizeObserverCallback) { resize = callback; }
    observe() {}
    disconnect() {}
  });
  const resizeRow = (target: Element) => resize!([{ target, contentRect: target.getBoundingClientRect(),
    borderBoxSize: [], contentBoxSize: [], devicePixelContentBoxSize: [] }], {} as ResizeObserver);
  function Harness() {
    const viewport = useRef<HTMLDivElement | null>(null);
    const view = useTranscriptWindow(messages, viewport);
    return <div ref={viewport} data-viewport><div ref={view.container} data-window>
      <div style={{ height: view.before }} />
      {view.rows.map(message => <div data-transcript-row={message.id} key={message.id}>{message.content}</div>)}
      <div style={{ height: view.after }} />
    </div></div>;
  }
  const container = document.createElement('div');
  document.body.append(container);
  const root = createRoot(container);
  const boundingRect = vi.spyOn(HTMLElement.prototype, 'getBoundingClientRect').mockImplementation(function(this: HTMLElement) {
    const viewport = container.querySelector('[data-viewport]') as HTMLElement | null;
    const id = this.dataset.transcriptRow;
    const top = this.hasAttribute('data-window') ? -(viewport?.scrollTop || 0)
      : id !== undefined ? Number(id) * 180 - (viewport?.scrollTop || 0) : 0;
    const height = id !== undefined ? heights.get(id) ?? 180 : 600;
    return { top, bottom: top + height, left: 0, right: 800, width: 800, height, x: 0, y: top, toJSON: () => ({}) };
  });
  try {
    await act(async () => { root.render(<Harness />); });
    const viewport = container.querySelector('[data-viewport]') as HTMLElement;
    Object.defineProperties(viewport, {
      clientHeight: { configurable: true, value: 600 },
      scrollHeight: { configurable: true, get: () => 36000 + [...heights.values()].reduce((sum, height) => sum + height - 180, 0) },
    });
    await act(async () => { viewport.scrollTop = 35400; viewport.dispatchEvent(new Event('scroll')); vi.advanceTimersByTime(20); });
    const last = container.querySelector('[data-transcript-row="199"]')!;
    await act(async () => {
      heights.set('199', 500);
      resizeRow(last);
    });
    expect(viewport.scrollTop).toBe(viewport.scrollHeight);

    await act(async () => { viewport.scrollTop = 18000; viewport.dispatchEvent(new Event('scroll')); vi.advanceTimersByTime(20); });
    const above = container.querySelector('[data-transcript-row]') as HTMLElement;
    expect(above.getBoundingClientRect().bottom).toBeLessThan(0);
    await act(async () => {
      heights.set(above.dataset.transcriptRow!, 320);
      resizeRow(above);
    });
    expect(viewport.scrollTop).toBe(18140);
  } finally {
    await act(async () => root.unmount());
    container.remove();
    boundingRect.mockRestore();
    vi.unstubAllGlobals();
    vi.useRealTimers();
  }
});
