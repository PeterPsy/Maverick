import { HTMLAttributes } from "react";
import { cx } from "./cx";

type SurfaceProps = HTMLAttributes<HTMLElement> & {
  as?: "article" | "div" | "section";
  interactive?: boolean;
};

export function Surface({ as = "div", className, interactive = false, ...props }: SurfaceProps) {
  const Component = as;
  return <Component {...props} className={cx("bs-ui-surface", interactive && "bs-ui-surface--interactive", className)} />;
}
