/** Keep downloads in the authenticated app frame, including native WebKit. */
export function startStorageDownload(url: string, fileName: string) {
  const anchor = document.createElement('a');
  anchor.href = url;
  anchor.download = fileName;
  anchor.hidden = true;
  document.body.appendChild(anchor);
  try {
    anchor.click();
  } finally {
    anchor.remove();
  }
}

export function downloadStorageBlob(blob: Blob, fileName: string) {
  const url = URL.createObjectURL(blob);
  try {
    startStorageDownload(url, fileName);
  } finally {
    // WebKit consumes the blob asynchronously after the click dispatch returns.
    window.setTimeout(() => URL.revokeObjectURL(url), 60_000);
  }
}
