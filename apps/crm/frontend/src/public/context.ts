/** Display mode only; the public server independently enforces every operation. */
export const publicAccess = document.documentElement.dataset.crmPublicAccess;
export const isPublicCrm = publicAccess === 'read-only' || publicAccess === 'read-write';
