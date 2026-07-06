import { type CSSProperties, useLayoutEffect, useRef, useState } from "react";

export function useDockedComposerHeight({
  attachmentCount,
  composerError,
  isComposerDockVisible,
  isEmptyChatView,
  queuedMessageCount,
}: {
  attachmentCount: number;
  composerError: string | null;
  isComposerDockVisible: boolean;
  isEmptyChatView: boolean;
  queuedMessageCount: number;
}) {
  const dockedComposerRef = useRef<HTMLDivElement | null>(null);
  const [dockedComposerHeight, setDockedComposerHeight] = useState(144);
  const canMeasureDock = !isEmptyChatView && isComposerDockVisible;
  const chatMainStyle = canMeasureDock
    ? ({
        "--chatapp-composer-overlay-height": `${dockedComposerHeight}px`,
      } as CSSProperties)
    : undefined;

  useLayoutEffect(() => {
    const dock = dockedComposerRef.current;
    if (!dock || !canMeasureDock) {
      return;
    }
    const updateDockHeight = () => {
      setDockedComposerHeight(Math.ceil(dock.getBoundingClientRect().height));
    };
    updateDockHeight();
    if (typeof ResizeObserver === "undefined") {
      window.addEventListener("resize", updateDockHeight);
      return () => window.removeEventListener("resize", updateDockHeight);
    }
    const observer = new ResizeObserver(updateDockHeight);
    observer.observe(dock);
    return () => observer.disconnect();
  }, [attachmentCount, canMeasureDock, composerError, queuedMessageCount]);

  return { chatMainStyle, dockedComposerHeight, dockedComposerRef };
}
