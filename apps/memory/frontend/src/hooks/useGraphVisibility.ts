import { useEffect, useState, type RefObject } from "react";

export function useGraphVisibility(container: RefObject<HTMLElement | null>) {
  const [visible, setVisible] = useState(!document.hidden);
  const reducedMotion = useReducedMotion();
  useEffect(() => {
    let inViewport = true;
    const update = () => setVisible(inViewport && !document.hidden);
    const observer = new IntersectionObserver(([entry]) => { inViewport = entry.isIntersecting; update(); });
    if (container.current) observer.observe(container.current);
    document.addEventListener("visibilitychange", update);
    return () => { observer.disconnect(); document.removeEventListener("visibilitychange", update); };
  }, [container]);
  return { visible, reducedMotion };
}

export function useReducedMotion() {
  const [reducedMotion, setReducedMotion] = useState(() => window.matchMedia("(prefers-reduced-motion: reduce)").matches);
  useEffect(() => {
    const media = window.matchMedia("(prefers-reduced-motion: reduce)");
    const update = () => setReducedMotion(media.matches);
    media.addEventListener("change", update);
    return () => media.removeEventListener("change", update);
  }, []);
  return reducedMotion;
}
