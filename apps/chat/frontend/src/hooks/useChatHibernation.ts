import { useEffect, useRef, useState } from 'react';
import { registerMaverickAppHibernation, type MaverickAppSnapshot, type MaverickResumeParams } from '@maverick/pwa-cache';
import { hasQueuedMessageMemory } from '../lib/queuedMessages';
import type { AppReference } from '../api/client';
import { useChatVisibility } from './useChatVisibility';

type Draft = { key: string; text: string; references: AppReference[]; settings: Record<string, string> };
type ReadingAnchor = { rowId: string; eventId: string; offset: number };
type ChatSnapshot = { drafts: Draft[]; key: string; scroll: number; visibleMessages: number; anchor?: ReadingAnchor | null };
type Pending = { snapshot: MaverickAppSnapshot; navigation: MaverickResumeParams; navigated?: boolean;
  resolve: () => void; reject: (error: unknown) => void };

function readingPosition() {
  const viewport = document.querySelector<HTMLElement>('.chatapp-chat-scroll__inner');
  if (!viewport || !viewport.clientHeight) return null;
  const top = viewport.getBoundingClientRect().top;
  const row = [...viewport.querySelectorAll<HTMLElement>('[data-transcript-row]:not([hidden])')]
    .find(element => element.dataset.runtimeEventId && element.getBoundingClientRect().bottom > top
      && element.getBoundingClientRect().top < top + viewport.clientHeight);
  return { top: viewport.scrollTop, anchor: row ? { rowId: row.dataset.transcriptRow!, eventId: row.dataset.runtimeEventId!,
    offset: row.getBoundingClientRect().top - top } : null };
}

export function useChatHibernation(options: {
  ready: boolean; historyReady: boolean; canHibernate: boolean; conversationKey: string;
  composer: string; references: AppReference[]; params: MaverickResumeParams;
  settings: Record<string, string>; visibleMessages: number;
  navigate: (params: MaverickResumeParams) => Promise<void>;
  restoreDraft: (draft: Draft) => void;
  setVisibleMessages: (count: number) => void;
  restoreHistory?: (eventId: string) => number;
  restoredHistoryRequestId?: number;
}) {
  const visible = useChatVisibility();
  const current = useRef(options);
  current.current = options;
  const drafts = useRef(new Map<string, Draft>());
  const scroll = useRef<{ key: string; top: number; anchor?: ReadingAnchor | null; requestId?: number } | null>(null);
  const lastPosition = useRef<{ key: string; top: number; anchor: ReadingAnchor | null } | null>(null);
  const running = useRef(false);
  const [pending, setPending] = useState<Pending | null>(null);

  useEffect(() => {
    if (!visible) return;
    const remember = () => {
      const position = readingPosition();
      if (position) lastPosition.current = { ...position, key: current.current.conversationKey };
    };
    document.addEventListener('scroll', remember, { capture: true, passive: true });
    remember();
    return () => document.removeEventListener('scroll', remember, true);
  }, [visible, options.conversationKey]);

  useEffect(() => registerMaverickAppHibernation({
    appId: 'chat',
    capture: () => {
      const value = current.current;
      if (!value.ready || !value.historyReady || !value.canHibernate || running.current || scroll.current?.key === value.conversationKey || hasQueuedMessageMemory()) return null;
      const saved = new Map(drafts.current);
      saved.set(value.conversationKey, { key: value.conversationKey, text: value.composer,
        references: value.references, settings: value.settings });
      const viewport = document.querySelector('.chatapp-chat-scroll__inner');
      const position = viewport ? readingPosition() || (lastPosition.current?.key === value.conversationKey ? lastPosition.current : null) : null;
      return { params: value.params, state: { drafts: [...saved.values()], key: value.conversationKey,
        visibleMessages: value.visibleMessages,
        anchor: position?.anchor,
        scroll: position?.top || 0 } satisfies ChatSnapshot };
    },
    restore: (snapshot, navigation) => new Promise<void>((resolve, reject) => {
      setPending({ snapshot, navigation, resolve, reject });
    }),
  }), []);

  useEffect(() => {
    if (!pending || pending.navigated || !options.ready || !visible || running.current) return;
    running.current = true;
    const saved = pending.snapshot.state as ChatSnapshot;
    if (!saved || !Array.isArray(saved.drafts) || typeof saved.key !== 'string'
      || (saved.anchor && (typeof saved.anchor.eventId !== 'string' || !saved.anchor.eventId || saved.anchor.eventId.length > 256
        || typeof saved.anchor.rowId !== 'string' || !saved.anchor.rowId || !Number.isFinite(saved.anchor.offset)))) {
      running.current = false;
      setPending(null);
      pending.reject(new Error('Invalid Chat resume state.'));
      return;
    }
    drafts.current = new Map(saved.drafts.map((draft) => [draft.key, draft]));
    scroll.current = { key: saved.key, top: Math.max(0, saved.scroll || 0), anchor: saved.anchor };
    const explicit = Object.entries(pending.navigation).some(([key, value]) => key !== 'workspace_id' && value !== null && value !== '');
    void current.current.navigate(explicit ? pending.navigation : pending.snapshot.params).then(() => {
      current.current.setVisibleMessages(Math.max(50, saved.visibleMessages || 50));
      running.current = false;
      setPending(current => current === pending ? { ...current, navigated: true } : current);
    }, (error) => {
      running.current = false;
      setPending(null);
      pending.reject(error);
    });
  }, [pending, options.ready, visible]);

  useEffect(() => {
    if (!options.ready || !visible || (pending && !pending.navigated) || running.current) return;
    const draft = drafts.current.get(options.conversationKey);
    if (draft) { drafts.current.delete(options.conversationKey); options.restoreDraft(draft); }
    if (scroll.current?.key !== options.conversationKey) {
      if (pending?.navigated) { setPending(null); pending.resolve(); }
      return;
    }
    if (!options.historyReady) return;
    const saved = scroll.current;
    if (saved.anchor && options.restoreHistory && saved.requestId === undefined) {
      saved.requestId = options.restoreHistory(saved.anchor.eventId);
      return;
    }
    if (saved.requestId !== undefined && options.restoredHistoryRequestId !== saved.requestId) return;
    let attempts = 0;
    let frame: number;
    const align = () => {
      const viewport = document.querySelector<HTMLElement>('.chatapp-chat-scroll__inner');
      if (!viewport) {
        scroll.current = null;
        if (pending) { setPending(null); pending.resolve(); }
        return;
      }
      if (saved.anchor) {
        const row = [...viewport.querySelectorAll<HTMLElement>('[data-transcript-row]:not([hidden])')]
          .find(element => element.dataset.transcriptRow === saved.anchor!.rowId);
        const delta = row ? row.getBoundingClientRect().top - viewport.getBoundingClientRect().top - saved.anchor.offset : null;
        if (delta === null || Math.abs(delta) >= 2) {
          if (++attempts > 60) {
            scroll.current = null;
            setPending(null);
            pending?.reject(new Error('Unable to restore the Chat reading position.'));
            return;
          }
          if (delta === null) viewport.dispatchEvent(new CustomEvent('chatapp.restore-reading-anchor', { detail: saved.anchor }));
          else viewport.scrollTop += delta;
          frame = requestAnimationFrame(align);
          return;
        }
      } else viewport.scrollTop = saved.top;
      viewport.dispatchEvent(new Event('scroll'));
      scroll.current = null;
      if (pending) { setPending(null); pending.resolve(); }
    };
    frame = requestAnimationFrame(align);
    return () => cancelAnimationFrame(frame);
  }, [options.ready, options.historyReady, options.conversationKey, options.restoredHistoryRequestId, pending, visible]);
}
