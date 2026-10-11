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
        colors={["#090a0c", "#161719", "#303438", "#4a4e52"]}
        speed={0.25}
        maxPixelCount={400000}
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
