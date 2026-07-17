export function LiveBorderGlow({ className = "" }: { className?: string }) {
  const classes = ["chatapp-live-border-glow", className].filter(Boolean).join(" ");
  return (
    <span aria-hidden="true" className={classes}>
      <span className="chatapp-live-border-glow__layer chatapp-live-border-glow__layer--outer" />
      <span className="chatapp-live-border-glow__layer chatapp-live-border-glow__layer--a" />
      <span className="chatapp-live-border-glow__layer chatapp-live-border-glow__layer--b" />
      <span className="chatapp-live-border-glow__layer chatapp-live-border-glow__layer--c" />
      <span className="chatapp-live-border-glow__layer chatapp-live-border-glow__layer--bright" />
      <span className="chatapp-live-border-glow__layer chatapp-live-border-glow__layer--rim" />
    </span>
  );
}
