import { ButtonHTMLAttributes, ReactNode } from "react";
import { cx } from "./cx";

type ButtonVariant = "primary" | "secondary" | "ghost";
type ButtonSize = "sm" | "md";

type ButtonProps = ButtonHTMLAttributes<HTMLButtonElement> & {
  children: ReactNode;
  fullWidth?: boolean;
  loading?: boolean;
  size?: ButtonSize;
  variant?: ButtonVariant;
};

export function Button({
  children,
  className,
  disabled,
  fullWidth = false,
  loading = false,
  size = "md",
  type = "button",
  variant = "secondary",
  ...props
}: ButtonProps) {
  return (
    <button
      {...props}
      aria-busy={loading || undefined}
      className={cx("bs-ui-button", `bs-ui-button--${variant}`, `bs-ui-button--${size}`, fullWidth && "bs-ui-button--full", className)}
      disabled={disabled || loading}
      type={type}
    >
      {loading ? <span className="bs-ui-button__spinner" aria-hidden="true" /> : null}
      <span>{children}</span>
    </button>
  );
}
