type BrandMarkVariant = "icon" | "mark" | "logotype";

const brandAssets: Record<BrandMarkVariant, string> = {
  icon: "/apps/base-shell/maverick-app-icon.svg",
  logotype: "/apps/base-shell/maverick-logotype.svg",
  mark: "/apps/base-shell/maverick-mark.svg",
};

export function BrandMark({
  alt = "Maverick",
  className = "",
  variant = "icon",
}: {
  alt?: string;
  className?: string;
  variant?: BrandMarkVariant;
}) {
  return <img alt={alt} className={className} src={brandAssets[variant]} />;
}
