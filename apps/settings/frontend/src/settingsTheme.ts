export function applySettingsTheme(value: unknown) {
  if (!value || typeof value !== 'object') return;
  const effective = (value as { effective?: unknown }).effective;
  if (effective !== 'dark' && effective !== 'light') return;
  const root = document.documentElement;
  root.dataset.loopinoTheme = effective;
  root.dataset.theme = effective;
  root.style.colorScheme = effective;
}
