import { useEffect, useState } from "react";
import type { CSSProperties } from "react";
import { calculateSidebarRailMetrics } from "../lib/sidebarRailMetrics";

type SidebarRailViewport = {
  rootFontSizePx: number | null;
  viewportHeightPx: number | null;
};

export function useSidebarRailMetrics(itemCount: number, isMobileLayout: boolean): CSSProperties {
  const [viewport, setViewport] = useState<SidebarRailViewport>(readSidebarRailViewport);

  useEffect(() => {
    if (typeof window === "undefined") {
      return undefined;
    }

    const sync = () => setViewport(readSidebarRailViewport());
    const visualViewport = window.visualViewport;

    sync();
    window.addEventListener("resize", sync);
    visualViewport?.addEventListener("resize", sync);
    return () => {
      window.removeEventListener("resize", sync);
      visualViewport?.removeEventListener("resize", sync);
    };
  }, []);

  if (isMobileLayout) {
    return calculateSidebarRailMetrics({ itemCount });
  }

  return calculateSidebarRailMetrics({
    itemCount,
    rootFontSizePx: viewport.rootFontSizePx,
    viewportHeightPx: viewport.viewportHeightPx,
  });
}

function readSidebarRailViewport(): SidebarRailViewport {
  if (typeof window === "undefined" || typeof document === "undefined") {
    return { rootFontSizePx: null, viewportHeightPx: null };
  }

  const rootFontSize = Number.parseFloat(window.getComputedStyle(document.documentElement).fontSize);
  return {
    rootFontSizePx: Number.isFinite(rootFontSize) && rootFontSize > 0 ? rootFontSize : 16,
    viewportHeightPx: window.visualViewport?.height ?? window.innerHeight,
  };
}
