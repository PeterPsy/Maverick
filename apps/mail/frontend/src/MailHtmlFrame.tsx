import { useCallback, useEffect, useMemo, useRef, useState } from 'react';

const EMAIL_FRAME_MIN_HEIGHT = 180;
const EMAIL_FRAME_MAX_HEIGHT = 12_000;
const EMAIL_FRAME_MAX_WIDTH = 3_200;

function emailSrcDoc(htmlBody: string) {
  return `<!doctype html>
<html>
<head>
  <meta charset="utf-8" />
  <meta http-equiv="Content-Security-Policy" content="default-src 'none'; script-src 'none'; style-src 'unsafe-inline'; img-src data: https: http:; connect-src 'none'; frame-src 'none'; object-src 'none'; base-uri 'none'; form-action 'none'" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <style>
    html,
    body {
      margin: 0;
      padding: 0;
      background: #ffffff;
    }

    body {
      overflow-wrap: normal;
      word-break: normal;
    }

    img {
      border: 0;
    }

    .mail-blocked-image {
      display: inline-flex;
      align-items: center;
      justify-content: center;
      min-width: 2rem;
      min-height: 2rem;
      border: 1px dashed #cbd5e1;
      border-radius: 6px;
      background: #f8fafc;
      color: #64748b;
      padding: 0 10px;
      box-sizing: border-box;
      font: 12px Arial, Helvetica, sans-serif;
    }

    .mail-quote-fold {
      margin: 12px 0 0;
    }

    .mail-quote-fold > summary {
      display: inline-flex;
      align-items: center;
      min-height: 24px;
      border-radius: 999px;
      background: #f1f5f9;
      color: #475569;
      cursor: pointer;
      padding: 0 10px;
      font: 12px Arial, Helvetica, sans-serif;
    }

    .mail-quote-fold[open] > summary {
      margin-bottom: 8px;
    }
  </style>
</head>
<body>${htmlBody}</body>
</html>`;
}

export function MailHtmlFrame({ htmlBody }: { htmlBody: string }) {
  const frameRef = useRef<HTMLIFrameElement | null>(null);
  const [height, setHeight] = useState(320);
  const [frameWidth, setFrameWidth] = useState<number | null>(null);
  const srcDoc = useMemo(() => emailSrcDoc(htmlBody), [htmlBody]);

  const resizeFrame = useCallback(() => {
    const frame = frameRef.current;
    const doc = frame?.contentDocument;
    if (!doc) {
      return;
    }
    const docElement = doc.documentElement;
    const body = doc.body;
    const contentHeight = Math.max(
      docElement.scrollHeight,
      docElement.offsetHeight,
      body?.scrollHeight || 0,
      body?.offsetHeight || 0
    );
    const contentWidth = Math.max(
      docElement.scrollWidth,
      docElement.offsetWidth,
      body?.scrollWidth || 0,
      body?.offsetWidth || 0
    );
    const parentWidth = frame.parentElement?.clientWidth || frame.clientWidth || 0;
    const nextHeight = Math.max(EMAIL_FRAME_MIN_HEIGHT, Math.min(EMAIL_FRAME_MAX_HEIGHT, Math.ceil(contentHeight)));
    const nextWidth = parentWidth && contentWidth > parentWidth + 1
      ? Math.min(EMAIL_FRAME_MAX_WIDTH, Math.ceil(contentWidth))
      : null;

    setHeight((current) => current === nextHeight ? current : nextHeight);
    setFrameWidth((current) => current === nextWidth ? current : nextWidth);
  }, []);

  useEffect(() => {
    setFrameWidth(null);
    const id = window.setTimeout(resizeFrame, 120);
    return () => window.clearTimeout(id);
  }, [srcDoc, resizeFrame]);

  useEffect(() => {
    if (!frameWidth) {
      return undefined;
    }
    const id = window.setTimeout(resizeFrame, 50);
    return () => window.clearTimeout(id);
  }, [frameWidth, resizeFrame]);

  useEffect(() => {
    const frame = frameRef.current;
    const doc = frame?.contentDocument;
    if (!doc) {
      return undefined;
    }
    let animationFrame = 0;
    const scheduleResize = () => {
      window.cancelAnimationFrame(animationFrame);
      animationFrame = window.requestAnimationFrame(resizeFrame);
    };
    const observer = typeof ResizeObserver === 'undefined' ? null : new ResizeObserver(scheduleResize);
    if (observer) {
      observer.observe(doc.documentElement);
      if (doc.body) {
        observer.observe(doc.body);
      }
    }
    doc.querySelectorAll('img').forEach((image) => {
      image.addEventListener('load', scheduleResize);
      image.addEventListener('error', scheduleResize);
    });
    scheduleResize();
    return () => {
      window.cancelAnimationFrame(animationFrame);
      observer?.disconnect();
      doc.querySelectorAll('img').forEach((image) => {
        image.removeEventListener('load', scheduleResize);
        image.removeEventListener('error', scheduleResize);
      });
    };
  }, [srcDoc, resizeFrame]);

  return (
    <iframe
      ref={frameRef}
      title="Email HTML message"
      className="message-html-frame"
      sandbox="allow-popups allow-popups-to-escape-sandbox allow-same-origin"
      srcDoc={srcDoc}
      style={{ height, width: frameWidth ? `${frameWidth}px` : undefined }}
      onLoad={resizeFrame}
    />
  );
}
