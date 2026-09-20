// @vitest-environment happy-dom
import { act, useState } from 'react';
import { createRoot } from 'react-dom/client';
import { afterEach, expect, it, vi } from 'vitest';
import { useChatHibernation } from './useChatHibernation';
import type { registerMaverickAppHibernation } from '@maverick/pwa-cache';
import { clearQueuedMessageMemory, rememberQueuedMessages } from '../lib/queuedMessages';

const lifecycle = vi.hoisted(() => ({ options: null as Parameters<typeof registerMaverickAppHibernation>[0] | null }));
vi.mock('@maverick/pwa-cache', async (importOriginal) => ({ ...await importOriginal<typeof import('@maverick/pwa-cache')>(),
  registerMaverickAppHibernation: (options: typeof lifecycle.options) => {
  lifecycle.options = options;
  return () => { lifecycle.options = null; };
} }));
afterEach(() => { clearQueuedMessageMemory(); vi.unstubAllGlobals(); });

it('waits for the restored data window and pauses alignment while hidden before acknowledging resume', async () => {
  const container = document.createElement('div');
  document.body.append(container);
  const root = createRoot(container);
  let acknowledge: (id: number) => void = () => {};
  const request = vi.fn(() => 7);
  const restored = vi.fn();
  function Harness() {
    const [ack, setAck] = useState(0);
    acknowledge = setAck;
    useChatHibernation({ ready: true, historyReady: true, canHibernate: true, conversationKey: 'thread:a',
      composer: '', references: [], params: { thread_id: 'a' }, settings: {}, visibleMessages: 50,
      navigate: async () => {}, restoreDraft: () => {}, setVisibleMessages: () => {},
      restoreHistory: request, restoredHistoryRequestId: ack,
    });
    return <div className="chatapp-chat-scroll__inner">
      {ack === 7 ? <div data-transcript-row="row-a" data-runtime-event-id="event-a" /> : null}
    </div>;
  }
  const rect = vi.spyOn(HTMLElement.prototype, 'getBoundingClientRect').mockImplementation(function(this: HTMLElement) {
    const top = this.dataset.transcriptRow ? 40 : 0;
    return { top, bottom: top + 80, left: 0, right: 600, width: 600, height: 80, x: 0, y: top, toJSON: () => ({}) };
  });
  try {
    await act(async () => root.render(<Harness />));
    await act(async () => {
      void Promise.resolve(lifecycle.options!.restore({ params: { thread_id: 'a' }, state: {
        drafts: [], key: 'thread:a', scroll: 4000, visibleMessages: 50,
        anchor: { rowId: 'row-a', eventId: 'event-a', offset: 40 },
      } }, {})).then(restored);
    });
    expect(request).toHaveBeenCalledExactlyOnceWith('event-a');
    expect(restored).not.toHaveBeenCalled();
    await act(async () => {
      Object.defineProperty(document, 'hidden', { configurable: true, value: true });
      document.dispatchEvent(new Event('visibilitychange'));
      acknowledge(7);
    });
    await act(async () => { await new Promise(resolve => requestAnimationFrame(resolve)); });
    expect(restored).not.toHaveBeenCalled();
    await act(async () => {
      Object.defineProperty(document, 'hidden', { configurable: true, value: false });
      document.dispatchEvent(new Event('visibilitychange'));
    });
    await act(async () => { await new Promise(resolve => requestAnimationFrame(resolve)); });
    expect(restored).toHaveBeenCalledOnce();
    expect(container.querySelector('.chatapp-chat-scroll__inner')!.scrollTop).not.toBe(4000);
    const rejected = vi.fn();
    await act(async () => {
      void Promise.resolve(lifecycle.options!.restore({ params: {}, state: {
        drafts: [], key: 'thread:a', scroll: 0, visibleMessages: 50,
        anchor: { rowId: 'row-a', eventId: '', offset: 0 },
      } }, {})).catch(rejected);
    });
    expect(rejected).toHaveBeenCalledWith(new Error('Invalid Chat resume state.'));
    expect(request).toHaveBeenCalledOnce();
  } finally {
    delete (document as unknown as Record<string, unknown>).hidden;
    await act(async () => root.unmount());
    container.remove();
    rect.mockRestore();
  }
});

it('restores a draft only in its conversation and retains it across an explicit different deep link', async () => {
  (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
  const container = document.createElement('div');
  document.body.append(container);
  const root = createRoot(container);
  let navigate: (key: string) => void = () => {};
  let text = '';
  let ready = true;
  function Harness() {
    const [key, setKey] = useState('thread:b');
    const [composer, setComposer] = useState('');
    text = composer;
    navigate = setKey;
    useChatHibernation({ ready, historyReady: true, canHibernate: true, conversationKey: key,
      composer, references: [], params: { thread_id: key.slice(7) }, settings: {}, visibleMessages: 50,
      navigate: async (params) => { setKey(`thread:${params.thread_id}`); },
      restoreDraft: (draft) => setComposer(draft.text), setVisibleMessages: () => {},
    });
    return <div className="chatapp-chat-scroll__inner" />;
  }
  try {
    await act(async () => root.render(<Harness />));
    const restored = vi.fn();
    await act(async () => {
      void Promise.resolve(lifecycle.options!.restore({ params: { thread_id: 'a' }, state: {
        drafts: [{ key: 'thread:a', text: 'unsent A', references: [], settings: {} }],
        key: 'thread:a', scroll: 400, visibleMessages: 150,
      } }, { thread_id: 'b' })).then(restored);
    });
    expect(restored).toHaveBeenCalledOnce();
    expect(text).toBe('');
    expect((lifecycle.options!.capture()!.state as { drafts: unknown[] }).drafts).toHaveLength(2);
    await act(async () => navigate('thread:a'));
    expect(text).toBe('unsent A');
    await act(async () => { await new Promise((resolve) => requestAnimationFrame(resolve)); });
    expect(container.querySelector<HTMLElement>('.chatapp-chat-scroll__inner')!.scrollTop).toBe(400);
    ready = false;
    await act(async () => root.render(<Harness />));
    expect(lifecycle.options!.capture()).toBeNull();
    ready = true;
    await act(async () => root.render(<Harness />));
    rememberQueuedMessages('another-conversation', [{ clientMessageId: 'queued', content: 'waiting', attachments: [], appReferences: [] }]);
    expect(lifecycle.options!.capture()).toBeNull();
  } finally { await act(async () => root.unmount()); container.remove(); }
});
