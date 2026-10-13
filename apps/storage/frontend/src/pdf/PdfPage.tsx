import { useEffect, useRef, useState } from 'react';
import type { PDFDocumentProxy, RenderTask } from 'pdfjs-dist';

export function PdfPage({ document, pageNumber, width, zoom }: {
  document: PDFDocumentProxy; pageNumber: number; width: number; zoom: number;
}) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  useEffect(() => {
    if (width <= 0) return;
    let active = true;
    let renderTask: RenderTask | undefined;
    setLoading(true);
    setError('');
    async function render() {
      const page = await document.getPage(pageNumber);
      if (!active) return;
      const canvas = canvasRef.current;
      const context = canvas?.getContext('2d');
      if (!canvas || !context) throw new Error('PDF canvas is unavailable.');
      const base = page.getViewport({ scale: 1 });
      const viewport = page.getViewport({ scale: Math.min(width, 1200) * zoom / base.width });
      const outputScale = Math.min(window.devicePixelRatio || 1, 2,
        Math.sqrt(16_000_000 / (viewport.width * viewport.height)));
      canvas.width = Math.max(1, Math.floor(viewport.width * outputScale));
      canvas.height = Math.max(1, Math.floor(viewport.height * outputScale));
      canvas.style.width = `${viewport.width}px`;
      canvas.style.height = `${viewport.height}px`;
      renderTask = page.render({
        canvas, canvasContext: context, viewport,
        transform: outputScale === 1 ? undefined : [outputScale, 0, 0, outputScale, 0, 0],
      });
      await renderTask.promise;
      if (active) setLoading(false);
    }
    void render().catch((reason: Error) => {
      if (active) { setLoading(false); setError(reason.message || 'Unable to render this page.'); }
    });
    return () => {
      active = false;
      renderTask?.cancel();
      // Page resources are shared by PDF.js; the loading task owns their lifetime.
    };
  }, [document, pageNumber, width, zoom]);

  return (
    <div className="pdf-preview__page" aria-busy={loading}>
      {loading ? <div className="pdf-preview__message" role="status">Loading page…</div> : null}
      {error ? <div className="pdf-preview__message" role="alert">{error}</div> : null}
      <canvas ref={canvasRef} role="img" aria-label={`PDF page ${pageNumber}`} hidden={loading || Boolean(error)} />
    </div>
  );
}
