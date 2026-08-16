import { useCallback, useEffect, useRef, useState } from 'react';

const SCROLL_IDLE_DELAY_MS = 900;

export type OverlayScrollbarMetrics = {
  canScroll: boolean;
  thumbHeight: number;
  thumbOffset: number;
};

const EMPTY_SCROLLBAR_METRICS: OverlayScrollbarMetrics = {
  canScroll: false,
  thumbHeight: 0,
  thumbOffset: 0
};

export function useTransientOverlayScrollbar() {
  const scrollRef = useRef<HTMLDivElement | null>(null);
  const scrollIdleTimerRef = useRef<number | null>(null);
  const [isScrolling, setIsScrolling] = useState(false);
  const [scrollbarMetrics, setScrollbarMetrics] = useState<OverlayScrollbarMetrics>(EMPTY_SCROLLBAR_METRICS);

  const refreshScrollbarMetrics = useCallback(() => {
    const nextMetrics = overlayScrollbarMetrics(scrollRef.current);
    setScrollbarMetrics((current) => sameMetrics(current, nextMetrics) ? current : nextMetrics);
  }, []);

  const handleScroll = useCallback(() => {
    const scrollElement = scrollRef.current;
    refreshScrollbarMetrics();
    if (!scrollElement || scrollElement.scrollHeight <= scrollElement.clientHeight + 1) {
      return;
    }
    setIsScrolling(true);
    if (scrollIdleTimerRef.current !== null) {
      window.clearTimeout(scrollIdleTimerRef.current);
    }
    scrollIdleTimerRef.current = window.setTimeout(() => {
      setIsScrolling(false);
      scrollIdleTimerRef.current = null;
    }, SCROLL_IDLE_DELAY_MS);
  }, [refreshScrollbarMetrics]);

  useEffect(() => {
    return () => {
      if (scrollIdleTimerRef.current !== null) {
        window.clearTimeout(scrollIdleTimerRef.current);
      }
    };
  }, []);

  return {
    handleScroll,
    isScrolling,
    refreshScrollbarMetrics,
    scrollRef,
    scrollbarMetrics
  };
}

export function overlayScrollbarMetrics(scrollElement: HTMLElement | null): OverlayScrollbarMetrics {
  if (!scrollElement) {
    return EMPTY_SCROLLBAR_METRICS;
  }
  const viewportHeight = scrollElement.clientHeight;
  const contentHeight = scrollElement.scrollHeight;
  const trackHeight = Math.max(0, viewportHeight - 8);
  const canScroll = viewportHeight > 0 && contentHeight > viewportHeight + 1;
  if (!canScroll || trackHeight <= 0) {
    return EMPTY_SCROLLBAR_METRICS;
  }
  const thumbHeight = Math.min(trackHeight, Math.max(28, Math.round(trackHeight * (viewportHeight / contentHeight))));
  const maxThumbOffset = Math.max(0, trackHeight - thumbHeight);
  const maxScrollOffset = Math.max(1, contentHeight - viewportHeight);
  const thumbOffset = Math.round((scrollElement.scrollTop / maxScrollOffset) * maxThumbOffset);
  return { canScroll, thumbHeight, thumbOffset };
}

function sameMetrics(left: OverlayScrollbarMetrics, right: OverlayScrollbarMetrics) {
  return left.canScroll === right.canScroll
    && left.thumbHeight === right.thumbHeight
    && left.thumbOffset === right.thumbOffset;
}
