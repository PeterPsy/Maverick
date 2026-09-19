import { ReactNode, useEffect, useRef } from 'react';

// A non-modal inspector keeps the originating list and navigation available.
export function RecordInspector({ children, recordKey }: { children: ReactNode; recordKey: string }) {
  const panel = useRef<HTMLElement>(null);
  useEffect(() => {
    const previous = document.activeElement as HTMLElement | null;
    panel.current?.focus();
    return () => { if (previous?.isConnected) previous.focus(); };
  }, []);
  useEffect(() => { panel.current?.scrollTo({ top: 0 }); }, [recordKey]);
  return <aside className="product-inspector" aria-label="Record inspector" ref={panel} tabIndex={-1}>{children}</aside>;
}
