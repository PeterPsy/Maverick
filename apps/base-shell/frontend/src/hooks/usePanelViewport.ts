import { useEffect, useState } from "react";

function read() {
  return {
    width: window.visualViewport?.width ?? window.innerWidth,
    rootFontSize: Number.parseFloat(getComputedStyle(document.documentElement).fontSize) || 16,
  };
}

export function usePanelViewport() {
  const [viewport, setViewport] = useState(read);
  useEffect(() => {
    const sync = () => setViewport(read());
    window.addEventListener("resize", sync);
    window.visualViewport?.addEventListener("resize", sync);
    return () => {
      window.removeEventListener("resize", sync);
      window.visualViewport?.removeEventListener("resize", sync);
    };
  }, []);
  return viewport;
}
