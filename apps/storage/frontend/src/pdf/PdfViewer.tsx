import { useEffect, useRef, useState } from 'react';
import type { PdfPreviewProps } from '../pdfPreview';
import { PdfPage } from './PdfPage';
import { usePdfDocument } from './usePdfDocument';

export default function PdfViewer({ previewUrl, fileName, fallback }: PdfPreviewProps) {
  const { document, error } = usePdfDocument(previewUrl);
  const viewportRef = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(0);
  const [pageNumber, setPageNumber] = useState(1);
  const [zoom, setZoom] = useState(1);
  const total = document?.numPages || 0;

  useEffect(() => {
    const viewport = viewportRef.current;
    if (!viewport) return;
    const resize = () => setWidth(Math.max(1, Math.floor(viewport.clientWidth - 24)));
    resize();
    const observer = new ResizeObserver(resize);
    observer.observe(viewport);
    return () => observer.disconnect();
  }, [error]);

  useEffect(() => {
    viewportRef.current?.scrollTo({ top: 0, left: 0 });
  }, [pageNumber]);

  if (error) return fallback ? fallback(error) : <div className="pdf-preview__message" role="alert">{error}</div>;
  return (
    <section className="pdf-preview" aria-label={`PDF preview for ${fileName}`}>
      <div className="pdf-preview__toolbar" role="toolbar" aria-label="PDF controls">
        <div className="pdf-preview__controls">
          <button type="button" aria-label="Previous page" disabled={pageNumber <= 1 || !total}
            onClick={() => setPageNumber((current) => current - 1)}>←</button>
          <label className="pdf-preview__page-number">
            <span>Page</span>
            <input aria-label="PDF page" type="number" min={1} max={total || 1} value={pageNumber} disabled={!total}
              onChange={(event) => {
                const value = event.currentTarget.valueAsNumber;
                if (Number.isInteger(value)) setPageNumber(Math.max(1, Math.min(total, value)));
              }} />
            <span aria-live="polite">/ {total || '…'}</span>
          </label>
          <button type="button" aria-label="Next page" disabled={!total || pageNumber >= total}
            onClick={() => setPageNumber((current) => current + 1)}>→</button>
        </div>
        <div className="pdf-preview__controls">
          <button type="button" aria-label="Zoom out" disabled={zoom <= 0.5 || !total}
            onClick={() => setZoom((current) => Math.max(0.5, current - 0.25))}>−</button>
          <button type="button" className="pdf-preview__fit" aria-label="Fit PDF to width" disabled={!total}
            onClick={() => setZoom(1)}>{Math.round(zoom * 100)}%</button>
          <button type="button" aria-label="Zoom in" disabled={zoom >= 2.5 || !total}
            onClick={() => setZoom((current) => Math.min(2.5, current + 0.25))}>+</button>
        </div>
      </div>
      <div className="pdf-preview__viewport" ref={viewportRef} tabIndex={0} aria-label="PDF page content">
        {document ? <PdfPage document={document} pageNumber={pageNumber} width={width} zoom={zoom} />
          : <div className="pdf-preview__message" role="status">Loading PDF…</div>}
      </div>
    </section>
  );
}
