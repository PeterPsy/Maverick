// Only a successful status from the exact extension-bound Browser document can
// request automatic setup. A launch URL or ready notification cannot authorize it.
export function createAutoConnect(start) {
  let attempted;
  return async shared => {
    if (shared.auto_connect !== true || typeof shared.sharing_id !== "string" || !shared.sharing_id || shared.sharing_id.length > 80 || shared.sharing_id === attempted) return;
    attempted = shared.sharing_id;
    await start();
  };
}
