export function bouncyToggleHtml(inputHtml: string, label: string, className = ''): string {
  return `<label class="settings-toggle settings-bouncy-toggle ${className}">
    ${inputHtml}
    <span class="settings-bouncy-toggle__label">${label}</span>
    <span class="settings-bouncy-toggle__track" aria-hidden="true">
      <span class="settings-bouncy-toggle__inner"></span>
      <span class="settings-bouncy-toggle__thumb"><span class="settings-bouncy-toggle__dot"></span></span>
    </span>
  </label>`;
}

export function bindBouncyToggles(root: ParentNode = document): void {
  root.querySelectorAll<HTMLElement>('.settings-bouncy-toggle').forEach((toggle) => {
    const setPressed = (pressed: boolean) => toggle.classList.toggle('is-pressed', pressed);
    toggle.addEventListener('pointerdown', () => setPressed(true));
    toggle.addEventListener('pointerup', () => setPressed(false));
    toggle.addEventListener('pointerleave', () => setPressed(false));
  });
}
