/** Playwright AI snapshots expose eN refs; locator uses the aria-ref engine. */
export function snapshotReferenceSelector(value) {
  const text = value.trim();
  return /^(?:f[0-9]+)?e[0-9]+$/.test(text) ? `aria-ref=${text}` : text;
}
