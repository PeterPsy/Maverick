import { useLayoutEffect, useMemo, useRef, useState, type RefObject } from 'react';
import type { ChatMessage } from '../api/client';

const ESTIMATED_HEIGHT = 180;
const OVERSCAN = 6;
const WINDOW_THRESHOLD = 120;

function rowAt(offsets: number[], value: number): number {
  let low = 0;
  let high = offsets.length - 1;
  while (low < high) {
    const middle = Math.ceil((low + high) / 2);
    if (offsets[middle] <= value) low = middle;
    else high = middle - 1;
  }
  return Math.min(low, offsets.length - 2);
}

/** Variable-height rows, one observer, no transcript truncation or new dependency. */
export function useTranscriptWindow(messages: ChatMessage[], viewport: RefObject<HTMLDivElement | null> | undefined, speakingMessageId: string | null = null) {
  const container = useRef<HTMLDivElement | null>(null);
  const heights = useRef(new Map<string, number>());
  const pendingScroll = useRef<{ bottom: boolean; delta: number } | null>(null);
  const [measurement, setMeasurement] = useState(0);
  const [scroll, setScroll] = useState<{ top: number; height: number } | null>(null);
  const enabled = Boolean(viewport && messages.length > WINDOW_THRESHOLD);
  const offsets = useMemo(() => {
    const result = [0];
    if (enabled) for (const message of messages) result.push(result.at(-1)! + (heights.current.get(message.id) ?? ESTIMATED_HEIGHT));
    return result;
  }, [messages, measurement, enabled]);
  const total = offsets.at(-1)!;
  const start = enabled ? Math.max(0, rowAt(offsets, scroll?.top ?? Math.max(0, total - 1000)) - OVERSCAN) : 0;
  const end = enabled ? Math.min(messages.length, rowAt(offsets, (scroll?.top ?? Math.max(0, total - 1000)) + (scroll?.height ?? 1000)) + OVERSCAN + 1) : messages.length;
  const rows = messages.slice(start, end);
  const offscreenSpeech = enabled && speakingMessageId && !rows.some(message => message.id === speakingMessageId)
    ? messages.find(message => message.id === speakingMessageId) : undefined;
  // Speech owns an Audio/AudioContext outside the DOM. Keep only its component
  // mounted when it leaves the window; its layout space is already in a spacer.
  if (offscreenSpeech) rows.push(offscreenSpeech);
  const rowIdentity = rows.map(message => message.id).join('\0');

  useLayoutEffect(() => {
    if (!enabled || !viewport?.current || !container.current) return;
    const element = viewport.current;
    let frame: number | null = null;
    const update = () => {
      frame = null;
      const origin = container.current!.getBoundingClientRect().top - element.getBoundingClientRect().top + element.scrollTop;
      setScroll({ top: Math.max(0, element.scrollTop - origin), height: element.clientHeight || 1000 });
    };
    const schedule = () => { if (frame === null) frame = requestAnimationFrame(update); };
    element.addEventListener('scroll', schedule, { passive: true });
    window.addEventListener('resize', schedule);
    schedule();
    return () => {
      element.removeEventListener('scroll', schedule);
      window.removeEventListener('resize', schedule);
      if (frame !== null) cancelAnimationFrame(frame);
    };
  }, [enabled, viewport]);

  useLayoutEffect(() => {
    if (!enabled || !container.current || !viewport?.current || typeof ResizeObserver === 'undefined') return;
    const element = viewport.current;
    const observer = new ResizeObserver((entries) => {
      let changed = false;
      let anchorDelta = 0;
      let heightDelta = 0;
      for (const entry of entries) {
        const row = entry.target as HTMLElement;
        const id = row.dataset.transcriptRow!;
        const height = row.getBoundingClientRect().height;
        const previous = heights.current.get(id) ?? ESTIMATED_HEIGHT;
        if (height <= 0 || Math.abs(height - previous) < 1) continue;
        heights.current.set(id, height);
        heightDelta += height - previous;
        if (row.getBoundingClientRect().bottom < element.getBoundingClientRect().top) anchorDelta += height - previous;
        changed = true;
      }
      if (changed) {
        // ResizeObserver runs after the rows change size. Compare against the
        // previous height so growing content cannot detach a reader at bottom.
        const nearBottom = element.scrollHeight - heightDelta - element.scrollTop - element.clientHeight < 96;
        pendingScroll.current = { bottom: nearBottom || Boolean(pendingScroll.current?.bottom),
          delta: (pendingScroll.current?.delta ?? 0) + anchorDelta };
        setMeasurement(value => value + 1);
      }
    });
    container.current.querySelectorAll('[data-transcript-row]').forEach(row => observer.observe(row));
    return () => observer.disconnect();
  }, [enabled, rowIdentity, viewport]);

  useLayoutEffect(() => {
    const adjustment = pendingScroll.current;
    pendingScroll.current = null;
    if (!adjustment || !viewport?.current) return;
    const element = viewport.current;
    if (adjustment.bottom) element.scrollTop = element.scrollHeight;
    else if (adjustment.delta) element.scrollTop += adjustment.delta;
  }, [measurement, viewport]);

  useLayoutEffect(() => {
    const ids = new Set(messages.map(message => message.id));
    for (const id of heights.current.keys()) if (!ids.has(id)) heights.current.delete(id);
  }, [messages]);

  return { container, enabled, rows, hiddenRowId: offscreenSpeech?.id, before: offsets[start] || 0, after: enabled ? total - offsets[end] : 0 };
}
