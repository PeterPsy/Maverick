import { useEffect, useMemo, useRef, useState } from 'react';
import type { DynamicViewPayload } from './types';

const MIN_HEIGHT = 1;
const DEFAULT_HEIGHT = 1;
const RESIZE_EVENT = 'maverick.dynamic_view.resize';

const HOST_CSS = `
html, body {
  margin: 0;
  padding: 0;
  max-width: 100%;
  overflow-x: hidden;
}
* { box-sizing: border-box; }
body {
  overflow-wrap: anywhere;
  word-break: break-word;
}
img, svg, canvas, video {
  display: block;
  max-width: 100% !important;
  height: auto !important;
}
table {
  display: block;
  width: 100% !important;
  max-width: 100%;
  overflow-x: auto;
}
pre, code {
  white-space: pre-wrap;
  overflow-wrap: anywhere;
}
`;

function clampHeight(value: number) {
  if (!Number.isFinite(value)) return DEFAULT_HEIGHT;
  return Math.max(MIN_HEIGHT, Math.ceil(value));
}

export function buildSrcDoc(payload: DynamicViewPayload, frameId: string) {
  const runtimePayload = JSON.stringify(
    {
      data: payload.data || {},
      dataBindings: payload.dataBindings || [],
      metadata: {
        id: payload.id,
        title: payload.title,
        summary: payload.summary || '',
        snapshotMode: payload.snapshotMode,
        frameId
      }
    },
    null,
    2
  );

  return [
    '<!doctype html>',
    "<html><head><meta charset='utf-8' />",
    "<meta name='viewport' content='width=device-width, initial-scale=1' />",
    `<style>${HOST_CSS}${payload.package.css || ''}</style>`,
    '</head><body>',
    payload.package.html,
    '<script>',
    `window.MaverickDynamicView = ${runtimePayload};`,
    "const maverickFrameId = window.MaverickDynamicView?.metadata?.frameId || '';",
    'function maverickDynamicViewContentHeight() {',
    '  const doc = document.documentElement;',
    '  const body = document.body;',
    '  const bodyTop = body?.getBoundingClientRect?.().top || 0;',
    "  const elementBottom = Array.from(body?.querySelectorAll('*') || []).reduce(function(max, element) {",
    '    const rect = element.getBoundingClientRect();',
    '    return Math.max(max, rect.bottom - bodyTop);',
    '  }, 0);',
    '  const fallbackHeight = Math.max(body?.scrollHeight || 0, body?.offsetHeight || 0, doc?.scrollHeight || 0);',
    '  return elementBottom > 0 ? elementBottom : fallbackHeight;',
    '}',
    'function reportMaverickDynamicViewHeight() {',
    '  const height = maverickDynamicViewContentHeight();',
    "  window.parent?.postMessage({ type: 'maverick.dynamic_view.resize', frameId: maverickFrameId, height }, '*');",
    '}',
    "window.addEventListener('error', function(event) {",
    "  document.body.setAttribute('data-maverick-error', String(event.message || 'runtime-error'));",
    '  reportMaverickDynamicViewHeight();',
    '});',
    "window.addEventListener('load', reportMaverickDynamicViewHeight);",
    "window.addEventListener('resize', reportMaverickDynamicViewHeight);",
    "if (typeof ResizeObserver !== 'undefined') {",
    '  const observer = new ResizeObserver(reportMaverickDynamicViewHeight);',
    '  if (document.documentElement) observer.observe(document.documentElement);',
    '  if (document.body) observer.observe(document.body);',
    '}',
    '</script>',
    `<script>${payload.package.javascript || ''}</script>`,
    '<script>reportMaverickDynamicViewHeight(); setTimeout(reportMaverickDynamicViewHeight, 32); setTimeout(reportMaverickDynamicViewHeight, 180);</script>',
    '</body></html>'
  ].join('');
}

export function DynamicViewFrame({ payload, title }: { payload: DynamicViewPayload; title?: string }) {
  const iframeRef = useRef<HTMLIFrameElement | null>(null);
  const [height, setHeight] = useState(DEFAULT_HEIGHT);
  const frameId = payload.id || payload.instanceId || 'dynamic-view';
  const srcDoc = useMemo(() => buildSrcDoc(payload, frameId), [frameId, payload]);

  useEffect(() => {
    function handleMessage(event: MessageEvent) {
      if (event.source !== iframeRef.current?.contentWindow) return;
      const data = event.data;
      if (!data || typeof data !== 'object') return;
      if ((data as { type?: string }).type !== RESIZE_EVENT) return;
      if ((data as { frameId?: string }).frameId !== frameId) return;
      setHeight(clampHeight(Number((data as { height?: number }).height)));
    }
    window.addEventListener('message', handleMessage);
    return () => window.removeEventListener('message', handleMessage);
  }, [frameId]);

  return (
    <iframe
      ref={iframeRef}
      className="dynamic-view-frame"
      sandbox="allow-scripts"
      scrolling="no"
      srcDoc={srcDoc}
      style={{ height }}
      title={title || payload.title}
    />
  );
}
