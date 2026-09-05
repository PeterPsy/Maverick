/** Unscoped snapshots cannot prove the current principal; delete without reading. */
export function purgeLegacyWorkspaceSnapshots(): void {
  try {
    for (let index = sessionStorage.length - 1; index >= 0; index -= 1) {
      const key = sessionStorage.key(index);
      if (key?.startsWith('website-studio:snapshot:')) sessionStorage.removeItem(key);
    }
  } catch { /* Storage may be unavailable in isolated frames. */ }
}
