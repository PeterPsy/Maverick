import { useEffect, useState } from "react";
import { MeshGradient } from "@paper-design/shaders-react";

export function LoginPaperBackground() {
  const [reducedMotion, setReducedMotion] = useState(prefersReducedMotion);

  useEffect(() => {
    if (typeof window === "undefined" || typeof window.matchMedia !== "function") {
      return undefined;
    }
    const media = window.matchMedia("(prefers-reduced-motion: reduce)");
    const onChange = () => setReducedMotion(media.matches);
    onChange();
    media.addEventListener("change", onChange);
    return () => media.removeEventListener("change", onChange);
  }, []);

  if (reducedMotion) {
    return <div className="bs-login-paper-bg is-static" aria-hidden="true" />;
  }

  return (
    <div className="bs-login-paper-bg" aria-hidden="true">
      <MeshGradient
        className="bs-login-paper-bg__shader"
        colors={["#000000", "#1a1a1a", "#333333", "#ffffff"]}
        speed={1}
        maxPixelCount={1600000}
      />
    </div>
  );
}

function prefersReducedMotion(): boolean {
  if (typeof window === "undefined" || typeof window.matchMedia !== "function") {
    return false;
  }
  return window.matchMedia("(prefers-reduced-motion: reduce)").matches;
}
