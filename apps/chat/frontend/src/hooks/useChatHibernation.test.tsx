// @vitest-environment happy-dom
import { act, useState } from 'react';
import { createRoot } from 'react-dom/client';
import { afterEach, expect, it, vi } from 'vitest';
import { useChatHibernation } from './useChatHibernation';
import type { registerMaverickAppHibernation } from '@maverick/pwa-cache';
import { clearQueuedMessageMemory, rememberQueuedMessages } from '../lib/queuedMessages';

const lifecycle = vi.hoisted(() => ({ options: null as Parameters<typeof registerMaverickAppHibernation>[0] | null }));
vi.mock('@maverick/pwa-cache', () => ({ registerMaverickAppHibernation: (options: typeof lifecycle.options) => {
  lifecycle.options = options;
  return () => { lifecycle.options = null; };
} }));
afterEach(() => { clearQueuedMessageMemory(); vi.unstubAllGlobals(); });

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
