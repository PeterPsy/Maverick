import * as Dialog from "@radix-ui/react-dialog";
import type { ReactNode } from "react";
import { Icon } from "../Icon";

export function Drawer({
  title,
  eyebrow,
  children,
  footer,
  saving,
  onClose,
}: {
  title: string;
  eyebrow: string;
  children: ReactNode;
  footer: ReactNode;
  saving: boolean;
  onClose: () => void;
}) {
  return (
    <Dialog.Root
      open
      onOpenChange={(open) => {
        if (!open && !saving) onClose();
      }}
    >
      <Dialog.Portal>
        <Dialog.Overlay className="drawer-overlay" />
        <Dialog.Content
          aria-describedby={undefined}
          className="record-drawer"
          onInteractOutside={(event) => {
            if (saving) event.preventDefault();
          }}
          onEscapeKeyDown={(event) => {
            if (saving) event.preventDefault();
          }}
        >
          <header className="panel-header">
            <div>
              <p className="eyebrow">{eyebrow}</p>
              <Dialog.Title className="drawer-title">{title}</Dialog.Title>
            </div>
            <Dialog.Close
              aria-label="Chiudi"
              className="icon-action"
              disabled={saving}
            >
              <Icon name="close" />
            </Dialog.Close>
          </header>
          <div className="drawer-body">{children}</div>
          <footer className="panel-footer">{footer}</footer>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
