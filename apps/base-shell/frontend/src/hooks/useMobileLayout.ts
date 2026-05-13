import { useEffect, useState } from "react";

export const MOBILE_LAYOUT_QUERY = "(max-width: 979px)";

export function getInitialMobileLayout(): boolean {
  return typeof window !== "undefined" && typeof window.matchMedia === "function" ? window.matchMedia(MOBILE_LAYOUT_QUERY).matches : false;
}

export function useMobileLayout() {
  const [isMobileLayout, setIsMobileLayout] = useState(getInitialMobileLayout);

  useEffect(() => {
    if (typeof window === "undefined" || typeof window.matchMedia !== "function") {
      return undefined;
    }

    const mediaQuery = window.matchMedia(MOBILE_LAYOUT_QUERY);
    const sync = () => setIsMobileLayout(mediaQuery.matches);

    sync();
    mediaQuery.addEventListener("change", sync);
    return () => mediaQuery.removeEventListener("change", sync);
  }, []);

  return isMobileLayout;
}
