import { escapeHtml } from './html';

export function confirmSettingsAction(options: { title: string; detail: string; confirmLabel: string }): Promise<boolean> {
  const previous = document.activeElement as HTMLElement | null;
  const dialog = document.createElement('dialog');
  dialog.className = 'settings-modal settings-confirm-dialog';
  dialog.setAttribute('aria-labelledby', 'settings-confirm-title');
  dialog.setAttribute('aria-describedby', 'settings-confirm-detail');
  dialog.innerHTML = `<h2 id="settings-confirm-title">${escapeHtml(options.title)}</h2>
    <p id="settings-confirm-detail" class="settings-card-copy">${escapeHtml(options.detail)}</p>
    <form method="dialog" class="settings-modal-actions">
      <button value="cancel" class="settings-secondary" autofocus>Cancel</button>
      <button value="confirm" class="settings-danger">${escapeHtml(options.confirmLabel)}</button>
    </form>`;
  document.body.append(dialog);
  return new Promise(resolve => {
    dialog.addEventListener('close', () => {
      const confirmed = dialog.returnValue === 'confirm';
      dialog.remove();
      if (previous?.isConnected) previous.focus();
      resolve(confirmed);
    }, { once: true });
    dialog.showModal();
  });
}

let previousFocus: HTMLElement | null = null;
let activeModal: HTMLElement | null = null;
export function syncSettingsModalFocus(cancel: () => void) {
  const modal = document.querySelector<HTMLElement>('.settings-modal[role="dialog"]');
  if (!modal) {
    if (activeModal && previousFocus?.isConnected) previousFocus.focus();
    activeModal = null;
    return;
  }
  const controls = () => Array.from(modal.querySelectorAll<HTMLElement>('button:not(:disabled), input:not(:disabled), select:not(:disabled), [tabindex="0"]'));
  if (activeModal !== modal) {
    previousFocus = document.activeElement as HTMLElement | null;
    activeModal = modal;
    controls()[0]?.focus();
  }
  modal.onkeydown = event => {
    if (event.key === 'Escape' && !modal.querySelector('button#close-migration-modal:disabled')) {
      event.preventDefault(); cancel();
    }
    if (event.key !== 'Tab') return;
    const items = controls();
    const first = items[0]; const last = items.at(-1);
    if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last?.focus(); }
    if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first?.focus(); }
  };
}
