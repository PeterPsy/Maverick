import { useEffect, useRef, useState, type ReactNode } from 'react';
import type { StorageFile } from '../../types';

const DOCX_MIME_TYPE = 'application/vnd.openxmlformats-officedocument.wordprocessingml.document';

export function isDocxFile(file: StorageFile | null | undefined): boolean {
  if (!file) return false;
  return file.name.toLowerCase().endsWith('.docx') || file.content_type.toLowerCase() === DOCX_MIME_TYPE;
}

interface DocxPreviewProps {
  blob: Blob;
  fallback: (reason: string) => ReactNode;
  fileName: string;
  onRendered?: () => void;
}

export function DocxPreview({ blob, fallback, fileName, onRendered }: DocxPreviewProps) {
  const bodyRef = useRef<HTMLDivElement | null>(null);
  const stylesRef = useRef<HTMLDivElement | null>(null);
  const onRenderedRef = useRef(onRendered);
  const [error, setError] = useState('');
  const [rendering, setRendering] = useState(true);

  useEffect(() => {
    onRenderedRef.current = onRendered;
  }, [onRendered]);

  useEffect(() => {
    const body = bodyRef.current;
    const styles = stylesRef.current;
    if (!body || !styles) return undefined;

    let active = true;
    const renderedBody = document.createElement('div');
    const renderedStyles = document.createElement('div');

    setError('');
    setRendering(true);
    body.replaceChildren();
    styles.replaceChildren();

    import('docx-preview')
      .then(({ renderAsync }) => renderAsync(blob, renderedBody, renderedStyles, {
        breakPages: true,
        ignoreFonts: false,
        ignoreHeight: false,
        ignoreLastRenderedPageBreak: false,
        ignoreWidth: false,
        inWrapper: true,
        renderAltChunks: false,
        renderComments: false,
        renderEndnotes: true,
        renderFooters: true,
        renderFootnotes: true,
        renderHeaders: true,
        useBase64URL: true,
      }))
      .then(() => {
        if (!active) return;
        styles.replaceChildren(...Array.from(renderedStyles.childNodes));
        body.replaceChildren(...Array.from(renderedBody.childNodes));
        setRendering(false);
        onRenderedRef.current?.();
      })
      .catch((renderError: unknown) => {
        if (!active) return;
        setRendering(false);
        setError(renderError instanceof Error ? renderError.message : `Unable to render ${fileName}.`);
      });

    return () => {
      active = false;
      body.replaceChildren();
      styles.replaceChildren();
    };
  }, [blob, fileName]);

  if (error) return <>{fallback(error)}</>;

  return (
    <div className="file-widget__docx-preview" aria-busy={rendering} aria-label={`Preview of ${fileName}`}>
      <div className="file-widget__docx-styles" ref={stylesRef} />
      <div className="file-widget__docx-body" ref={bodyRef} />
      {rendering ? (
        <div className="file-widget__docx-loading" aria-label="Loading document preview">
          <span />
          <span />
          <span />
          <span />
        </div>
      ) : null}
    </div>
  );
}
