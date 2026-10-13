import { lazy, Suspense, type ReactNode } from 'react';
import './styles/pdf-preview.css';

const PdfViewer = lazy(() => import('./pdf/PdfViewer'));

export type PdfPreviewProps = {
  previewUrl: string;
  fileName: string;
  fallback?: (reason: string) => ReactNode;
};

export function PdfPreview(props: PdfPreviewProps) {
  return (
    <Suspense fallback={<div className="pdf-preview__message" role="status">Loading PDF…</div>}>
      <PdfViewer key={props.previewUrl} {...props} />
    </Suspense>
  );
}
