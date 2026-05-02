interface MorphingSpinnerProps {
  size?: "sm" | "md" | "lg";
  className?: string;
}

const sizeClasses = {
  sm: "chatapp-morphing-spinner--sm",
  md: "chatapp-morphing-spinner--md",
  lg: "chatapp-morphing-spinner--lg",
};

function classNames(...values: Array<string | undefined>) {
  return values.filter(Boolean).join(" ");
}

export function MorphingSpinner({ size = "md", className }: MorphingSpinnerProps) {
  return (
    <span className={classNames("chatapp-morphing-spinner", sizeClasses[size], className)} aria-hidden="true">
      <span className="chatapp-morphing-spinner__shape" />
    </span>
  );
}
