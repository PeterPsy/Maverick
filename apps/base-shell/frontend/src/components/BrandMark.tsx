type BrandMarkVariant = "icon" | "mark" | "logotype";

const brandAssets: Record<BrandMarkVariant, string> = {
  icon: "/apps/base-shell/app-icon-lightcolor.png",
  logotype: "/apps/base-shell/loopino-logotype.svg",
  mark: "/apps/base-shell/loopino-mark.svg",
};

export function BrandMark({
  alt = "Loopino",
  className = "",
  variant = "icon",
}: {
  alt?: string;
  className?: string;
  variant?: BrandMarkVariant;
}) {
  return <img alt={alt} className={className} src={brandAssets[variant]} />;
}
