import { useEffect, useState } from 'react';
import { iconForKind, kindLabels } from './galleryMeta';
import { loadCardPreview } from './previewCache';
import type { GalleryFile } from './types';

export function canTextPreview(file: GalleryFile) {
  return ['text', 'markdown', 'document', 'presentation', 'spreadsheet'].includes(file.preview_kind);
}

export function canInlinePreview(file: GalleryFile) {
  return ['image', 'video', 'audio', 'text', 'markdown', 'pdf'].includes(file.preview_kind);
}

function FileTypeFallback({ file }: { file: GalleryFile }) {
  return (
    <div className="file-type-preview">
      <span className="gallery-card-icon material-symbols-rounded" aria-hidden="true">{iconForKind(file.preview_kind)}</span>
      <strong>{file.extension ? file.extension.replace('.', '').toUpperCase() : kindLabels[file.preview_kind]}</strong>
    </div>
  );
}

export function GalleryPreview({ file, previewUrl, previewText }: { file: GalleryFile; previewUrl: string; previewText: string }) {
  if (file.preview_kind === 'image' && previewUrl) return <img src={previewUrl} alt={file.name} />;
  if (file.preview_kind === 'video' && previewUrl) return <video src={previewUrl} controls />;
  if (file.preview_kind === 'audio' && previewUrl) return <audio src={previewUrl} controls />;
  if (file.preview_kind === 'pdf' && previewUrl) return <iframe src={previewUrl} title={file.name} />;
  if (['text', 'markdown'].includes(file.preview_kind)) return <pre>{previewText || 'Loading preview...'}</pre>;
  if (['document', 'presentation', 'spreadsheet'].includes(file.preview_kind) && previewText) return <pre>{previewText}</pre>;
  return (
    <div className="format-preview">
      <span className="material-symbols-rounded" aria-hidden="true">{iconForKind(file.preview_kind)}</span>
      <strong>{kindLabels[file.preview_kind]}</strong>
      <p>{file.name}</p>
      <small>Preview metadata is available. Download this file to open it with the native editor or viewer.</small>
    </div>
  );
}

export function FileCardPreview({ file }: { file: GalleryFile }) {
  const [previewUrl, setPreviewUrl] = useState('');
  const [previewText, setPreviewText] = useState('');
  const [previewFailed, setPreviewFailed] = useState(false);

  useEffect(() => {
    setPreviewUrl('');
    setPreviewText('');
    setPreviewFailed(false);
    if (!canInlinePreview(file) && !canTextPreview(file)) return;
    let active = true;
    loadCardPreview(file)
      .then((payload) => {
        if (!active) return;
        setPreviewText(payload.text);
        setPreviewUrl(payload.url);
      })
      .catch(() => {
        if (active) setPreviewFailed(true);
    });
    return () => {
      active = false;
    };
  }, [file]);

  if (previewFailed || (!canInlinePreview(file) && !canTextPreview(file))) {
    return <FileTypeFallback file={file} />;
  }
  if (file.preview_kind === 'image' && previewUrl) {
    return <img src={previewUrl} alt="" loading="lazy" />;
  }
  if (file.preview_kind === 'video' && previewUrl) {
    return <video src={previewUrl} muted playsInline preload="metadata" />;
  }
  if (file.preview_kind === 'audio' && previewUrl) {
    return <FileTypeFallback file={file} />;
  }
  if (file.preview_kind === 'pdf' && previewUrl) {
    return <iframe src={previewUrl} title={`${file.name} preview`} tabIndex={-1} />;
  }
  if (['text', 'markdown', 'document', 'presentation', 'spreadsheet'].includes(file.preview_kind)) {
    return previewText ? <pre>{previewText}</pre> : <FileTypeFallback file={file} />;
  }
  return <FileTypeFallback file={file} />;
}
