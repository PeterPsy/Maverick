import { type CSSProperties, useEffect, useRef, useState } from "react";

export function useDockedComposerHeight({
  attachmentCount,
  composerError,
  isEmptyChatView,
  queuedMessageCount,
}: {
  attachmentCount: number;
  composerError: string | null;
  isEmptyChatView: boolean;
  queuedMessageCount: number;
}) {
  const dockedComposerRef = useRef<HTMLDivElement | null>(null);
  const [dockedComposerHeight, setDockedComposerHeight] = useState(144);
  const chatMainStyle = isEmptyChatView
    ? undefined
    : ({
        "--chatapp-composer-overlay-height": `${dockedComposerHeight}px`,
      } as CSSProperties);

  useEffect(() => {
    const dock = dockedComposerRef.current;
    if (!dock || isEmptyChatView) {
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
  }, [attachmentCount, composerError, isEmptyChatView, queuedMessageCount]);

  return { chatMainStyle, dockedComposerRef };
}
