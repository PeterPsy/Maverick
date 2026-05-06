import { ReactNode, useEffect } from "react";
import { cx } from "./cx";

type DialogProps = {
  children: ReactNode;
  description?: string;
  dismissible?: boolean;
  hideHeader?: boolean;
  onClose: () => void;
  open: boolean;
  panelClassName?: string;
  title: string;
};

export function Dialog({ children, description, dismissible = true, hideHeader = false, onClose, open, panelClassName, title }: DialogProps) {
  useEffect(() => {
    if (!open) {
      return undefined;
    }

    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";

    const handleKeyDown = (event: KeyboardEvent) => {
      if (dismissible && event.key === "Escape") {
        onClose();
      }
    };

    window.addEventListener("keydown", handleKeyDown);

    return () => {
      document.body.style.overflow = previousOverflow;
      window.removeEventListener("keydown", handleKeyDown);
    };
  }, [dismissible, onClose, open]);

  if (!open) {
    return null;
  }

  return (
    <div className="bs-ui-dialog" role="dialog" aria-modal="true" aria-label={title}>
      <button
        aria-label="Close window"
        className="bs-ui-dialog__backdrop"
        disabled={!dismissible}
        onClick={dismissible ? onClose : undefined}
        type="button"
      />
      <div className={cx("bs-ui-dialog__panel", panelClassName)}>
        {!hideHeader ? (
          <div className="bs-ui-dialog__header">
            <div>
              <p className="bs-ui-dialog__eyebrow">Maverick</p>
              <h3 className="bs-ui-dialog__title">{title}</h3>
              {description ? <p className="bs-ui-dialog__description">{description}</p> : null}
            </div>
            {dismissible ? (
              <button aria-label="Close window" className="bs-ui-dialog__close" onClick={onClose} type="button">
                <span aria-hidden="true" className="material-symbols-rounded">close</span>
              </button>
            ) : null}
          </div>
        ) : null}
        {children}
      </div>
    </div>
  );
}
