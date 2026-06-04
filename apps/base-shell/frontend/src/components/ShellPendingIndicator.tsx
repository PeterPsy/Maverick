type ShellPendingIndicatorProps = {
  ariaLabel?: string;
  className?: string;
  label?: string;
  size?: "sm" | "md";
};

const sizeClasses = {
  sm: "bs-shell-pending-indicator--sm",
  md: "bs-shell-pending-indicator--md",
};

function classNames(...values: Array<string | undefined>) {
  return values.filter(Boolean).join(" ");
}

export function ShellPendingIndicator({
  ariaLabel,
  className,
  label = "Loading",
  size = "md",
}: ShellPendingIndicatorProps) {
  return (
    <div
      aria-label={ariaLabel || label}
      className={classNames("bs-shell-pending-indicator", sizeClasses[size], className)}
      role="status"
    >
      <span className="bs-shell-pending-indicator__icon" aria-hidden="true">
        <span className="bs-shell-pending-indicator__shape" />
      </span>
      <span className="bs-shell-pending-indicator__label">{label}</span>
    </div>
  );
}
