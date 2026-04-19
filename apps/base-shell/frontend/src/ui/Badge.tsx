import { HTMLAttributes, ReactNode } from "react";
import { cx } from "./cx";

type BadgeTone = "neutral" | "primary" | "success" | "warning" | "danger";

type BadgeProps = HTMLAttributes<HTMLSpanElement> & {
  children: ReactNode;
  tone?: BadgeTone;
};

export function Badge({ children, className, tone = "neutral", ...props }: BadgeProps) {
  return (
    <span {...props} className={cx("bs-ui-badge", `bs-ui-badge--${tone}`, className)}>
      {children}
    </span>
  );
}
