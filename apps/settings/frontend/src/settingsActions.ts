export async function runSettingsAction(region: HTMLElement | null, action: () => Promise<void>, reportError: (error: unknown) => void) {
  if (!region || region.hasAttribute('data-pending-action')) return;
  const controls = Array.from(region.querySelectorAll<HTMLInputElement | HTMLButtonElement | HTMLSelectElement>('input, button, select'));
  const disabled = controls.map(control => control.disabled);
  region.setAttribute('data-pending-action', '');
  region.setAttribute('aria-busy', 'true');
  const status = region.querySelector<HTMLElement>('[data-action-status]');
  if (status) { status.setAttribute('role', 'status'); status.textContent = 'Saving…'; }
  try {
    // Let the synchronous part capture FormData before disabling fields.
    const operation = action();
    controls.forEach(control => { control.disabled = true; });
    await operation;
    if (status) status.textContent = 'Saved.';
  } catch (error) {
    if (status) { status.setAttribute('role', 'alert'); status.textContent = error instanceof Error ? error.message : 'Unable to save.'; }
    reportError(error);
  } finally {
    region.removeAttribute('data-pending-action');
    region.removeAttribute('aria-busy');
    controls.forEach((control, index) => { control.disabled = disabled[index]; });
  }
}
