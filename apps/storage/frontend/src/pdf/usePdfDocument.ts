import { useEffect, useState } from 'react';
import { getDocument, GlobalWorkerOptions, type PDFDocumentProxy } from 'pdfjs-dist';
import pdfWorkerUrl from 'pdfjs-dist/build/pdf.worker.min.mjs?url';

// Vite resolves this against the public bundle URL, including in isolated widgets.
GlobalWorkerOptions.workerSrc = pdfWorkerUrl;

export function usePdfDocument(previewUrl: string) {
  const [document, setDocument] = useState<PDFDocumentProxy | null>(null);
  const [error, setError] = useState('');

  useEffect(() => {
    let active = true;
    setDocument(null);
    setError('');
    const task = getDocument({ url: previewUrl, withCredentials: true });
    task.onPassword = () => {
      if (active) setError('This PDF requires a password. Download it to open it.');
      void task.destroy().catch(() => {});
    };
    task.promise.then((loaded) => {
      if (active) setDocument(loaded);
    }).catch((reason: Error) => {
      if (active) setError((current) => current || reason.message || 'Unable to load this PDF.');
    });
    return () => {
      active = false;
      void task.destroy().catch(() => {});
    };
  }, [previewUrl]);

  return { document, error };
}
