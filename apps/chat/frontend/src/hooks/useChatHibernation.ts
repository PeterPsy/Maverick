import { useEffect, useRef, useState } from 'react';
import { registerMaverickAppHibernation, type MaverickAppSnapshot, type MaverickResumeParams } from '@maverick/pwa-cache';
import { hasQueuedMessageMemory } from '../lib/queuedMessages';
import type { AppReference } from '../api/client';

type Draft = { key: string; text: string; references: AppReference[]; settings: Record<string, string> };
type ChatSnapshot = { drafts: Draft[]; key: string; scroll: number; visibleMessages: number };
type Pending = { snapshot: MaverickAppSnapshot; navigation: MaverickResumeParams; resolve: () => void; reject: (error: unknown) => void };

export function useChatHibernation(options: {
  ready: boolean; historyReady: boolean; canHibernate: boolean; conversationKey: string;
  composer: string; references: AppReference[]; params: MaverickResumeParams;
  settings: Record<string, string>; visibleMessages: number;
  navigate: (params: MaverickResumeParams) => Promise<void>;
  restoreDraft: (draft: Draft) => void;
  setVisibleMessages: (count: number) => void;
}) {
  const current = useRef(options);
  current.current = options;
  const drafts = useRef(new Map<string, Draft>());
  const scroll = useRef<{ key: string; top: number } | null>(null);
  const running = useRef(false);
  const [pending, setPending] = useState<Pending | null>(null);

  useEffect(() => registerMaverickAppHibernation({
    appId: 'chat',
    capture: () => {
      const value = current.current;
      if (!value.ready || !value.canHibernate || running.current || hasQueuedMessageMemory()) return null;
      const saved = new Map(drafts.current);
      saved.set(value.conversationKey, { key: value.conversationKey, text: value.composer,
        references: value.references, settings: value.settings });
      return { params: value.params, state: { drafts: [...saved.values()], key: value.conversationKey,
        visibleMessages: value.visibleMessages,
        scroll: document.querySelector<HTMLElement>('.chatapp-chat-scroll__inner')?.scrollTop || 0 } satisfies ChatSnapshot };
    },
    restore: (snapshot, navigation) => new Promise<void>((resolve, reject) => {
      setPending({ snapshot, navigation, resolve, reject });
    }),
  }), []);

  useEffect(() => {
    if (!pending || !options.ready || running.current) return;
    running.current = true;
    const saved = pending.snapshot.state as ChatSnapshot;
    if (!saved || !Array.isArray(saved.drafts) || typeof saved.key !== 'string') {
      running.current = false;
      setPending(null);
      pending.reject(new Error('Invalid Chat resume state.'));
      return;
    }
    drafts.current = new Map(saved.drafts.map((draft) => [draft.key, draft]));
    scroll.current = { key: saved.key, top: Math.max(0, saved.scroll || 0) };
    const explicit = Object.entries(pending.navigation).some(([key, value]) => key !== 'workspace_id' && value !== null && value !== '');
    void current.current.navigate(explicit ? pending.navigation : pending.snapshot.params).then(() => {
      current.current.setVisibleMessages(Math.max(50, saved.visibleMessages || 50));
      running.current = false;
      setPending(null);
      pending.resolve();
    }, (error) => {
      running.current = false;
      setPending(null);
      pending.reject(error);
    });
  }, [pending, options.ready]);

  useEffect(() => {
    if (!options.ready || pending || running.current) return;
    const draft = drafts.current.get(options.conversationKey);
    if (draft) { drafts.current.delete(options.conversationKey); options.restoreDraft(draft); }
    if (!options.historyReady || scroll.current?.key !== options.conversationKey) return;
    const saved = scroll.current;
    const frame = requestAnimationFrame(() => {
      const viewport = document.querySelector<HTMLElement>('.chatapp-chat-scroll__inner');
      if (!viewport) return;
      viewport.scrollTop = saved.top;
      viewport.dispatchEvent(new Event('scroll'));
      scroll.current = null;
    });
    return () => cancelAnimationFrame(frame);
  }, [options.ready, options.historyReady, options.conversationKey, pending]);
}
