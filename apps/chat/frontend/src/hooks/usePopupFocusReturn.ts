import { useLayoutEffect, useRef, type RefObject } from "react";

export function usePopupFocusReturn(isOpen: boolean, triggerRef: RefObject<HTMLElement | null>) {
  const pendingRef = useRef(false);
  useLayoutEffect(() => {
    if (!isOpen && pendingRef.current) {
      pendingRef.current = false;
      // Compact utility panels hide their triggers until the popup is removed.
      triggerRef.current?.focus({ preventScroll: true });
    }
  }, [isOpen, triggerRef]);
  return () => {
    pendingRef.current = true;
  };
}
