import { useEffect, useRef, useState } from 'react';
import { FileCard, type FileCardFormat } from './components/ui/file-card-collections';
import { iconForKind, kindLabels } from './storageMeta';
import { Icon } from './Icon';
import { MarkdownPreview } from './markdownPreview';
import { loadCardPreview } from './previewCache';
import type { StorageFile, PreviewTablePayload, TablePreviewSheet } from './types';

export function canTextPreview(file: StorageFile) {
  return ['text', 'markdown'].includes(file.preview_kind);
}

export function canTablePreview(file: StorageFile) {
  return file.preview_kind === 'spreadsheet' || file.extension.toLowerCase() === '.csv';
}

export function canInlinePreview(file: StorageFile) {
  return ['image', 'video', 'audio', 'text', 'markdown', 'pdf', 'document', 'presentation', 'spreadsheet'].includes(file.preview_kind);
}

function canCardAssetPreview(file: StorageFile) {
  return file.preview_kind === 'image' || file.preview_kind === 'video';
}

function fileCardFormatForFile(file: StorageFile): FileCardFormat {
  const extension = file.extension.toLowerCase().replace(/^\./, '');
  if (extension === 'doc' || extension === 'docx') return 'doc';
  if (extension === 'pdf') return 'pdf';
  if (extension === 'md' || extension === 'mdx') return extension;
  if (extension === 'csv') return 'csv';
  if (extension === 'xls' || extension === 'xlsx') return extension;
  if (extension === 'txt') return 'txt';
  if (extension === 'ppt' || extension === 'pptx') return extension;
  if (extension === 'zip' || extension === 'rar' || extension === 'tar' || extension === 'gz') return extension;
  if (extension === 'html' || extension === 'js' || extension === 'jsx' || extension === 'tsx' || extension === 'css' || extension === 'json') return extension;
  if (extension === 'png' || extension === 'jpg' || extension === 'jpeg') return extension;
  if (file.preview_kind === 'audio') return 'audio';
  if (file.preview_kind === 'document') return 'doc';
  if (file.preview_kind === 'file') return 'zip';
  if (file.preview_kind === 'image') return 'img';
  if (file.preview_kind === 'markdown') return 'md';
  if (file.preview_kind === 'pdf') return 'pdf';
  if (file.preview_kind === 'presentation') return 'ppt';
  if (file.preview_kind === 'spreadsheet') return 'xls';
  if (file.preview_kind === 'text') return 'txt';
  if (file.preview_kind === 'video') return 'video';
  return 'code';
}

function columnLabel(index: number) {
  let value = index + 1;
  let label = '';
  while (value > 0) {
    const remainder = (value - 1) % 26;
    label = String.fromCharCode(65 + remainder) + label;
    value = Math.floor((value - 1) / 26);
  }
  return label;
}

function SpreadsheetSheet({ sheet, compact }: { sheet: TablePreviewSheet; compact: boolean }) {
  const columnCount = Math.max(1, ...sheet.rows.map((row) => row.length));
  return (
    <section className="spreadsheet-sheet">
      {!compact ? (
        <header className="spreadsheet-sheet-header">
          <strong>{sheet.name}</strong>
          {(sheet.truncated_rows || sheet.truncated_columns) ? <small>Preview limited to the first rows and columns.</small> : null}
        </header>
      ) : null}
      <div className="spreadsheet-scroll">
        <table className="spreadsheet-table">
          <thead>
            <tr>
              <th className="spreadsheet-corner" aria-label="Row number" />
              {Array.from({ length: columnCount }, (_, index) => <th key={index}>{columnLabel(index)}</th>)}
            </tr>
          </thead>
          <tbody>
            {sheet.rows.map((row, rowIndex) => (
              <tr key={rowIndex}>
                <th>{rowIndex + 1}</th>
                {Array.from({ length: columnCount }, (_, cellIndex) => <td key={cellIndex}>{row[cellIndex] || ''}</td>)}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}

function SpreadsheetPreview({ table, compact = false }: { table?: PreviewTablePayload; compact?: boolean }) {
  const sheets = table?.sheets.filter((sheet) => sheet.rows.length) || [];
  if (!sheets.length) {
    return (
      <div className={compact ? 'spreadsheet-empty compact' : 'spreadsheet-empty'}>
        <Icon name="table" />
        <strong>No tabular preview available</strong>
      </div>
    );
  }
  return (
    <div className={compact ? 'spreadsheet-preview compact' : 'spreadsheet-preview'}>
      {sheets.map((sheet) => <SpreadsheetSheet key={sheet.name} sheet={sheet} compact={compact} />)}
    </div>
  );
}

function FileTypeFallback({ file, loading = false }: { file: StorageFile; loading?: boolean }) {
  return (
    <div className={`file-type-preview file-type-card-preview storage-file-card-scope ${loading ? 'is-loading-preview' : ''}`}>
      <FileCard formatFile={fileCardFormatForFile(file)} />
    </div>
  );
}

type ImageSize = {
  width: number;
  height: number;
};

function fitImageToBox(image: ImageSize, box: ImageSize) {
  if (image.width <= 0 || image.height <= 0 || box.width <= 0 || box.height <= 0) return null;
  const scale = Math.min(box.width / image.width, box.height / image.height);
  if (!Number.isFinite(scale) || scale <= 0) return null;
  return {
    width: Math.max(1, Math.floor(image.width * scale)),
    height: Math.max(1, Math.floor(image.height * scale))
  };
}

function CardImagePreview({ src }: { src: string }) {
  const frameRef = useRef<HTMLSpanElement | null>(null);
  const [frameSize, setFrameSize] = useState<ImageSize | null>(null);
  const [imageSize, setImageSize] = useState<ImageSize | null>(null);
  const fittedSize = imageSize && frameSize ? fitImageToBox(imageSize, frameSize) : null;

  useEffect(() => {
    setImageSize(null);
  }, [src]);

  useEffect(() => {
    const frame = frameRef.current;
    if (!frame) return;
    const observedFrame = frame;

    function updateFrameSize() {
      const rect = observedFrame.getBoundingClientRect();
      const nextSize = {
        width: Math.max(0, Math.floor(rect.width)),
        height: Math.max(0, Math.floor(rect.height))
      };
      setFrameSize((current) => (
        current?.width === nextSize.width && current?.height === nextSize.height ? current : nextSize
      ));
    }

    updateFrameSize();
    const observer = new ResizeObserver(updateFrameSize);
    observer.observe(observedFrame);
    return () => observer.disconnect();
  }, []);

  return (
    <span className="animated-file-preview-image-frame" ref={frameRef}>
      <img
        className="animated-file-preview-image"
        src={src}
        alt=""
        loading="lazy"
        style={fittedSize ? { width: `${fittedSize.width}px`, height: `${fittedSize.height}px` } : undefined}
        onLoad={(event) => {
          const image = event.currentTarget;
          setImageSize({ width: image.naturalWidth, height: image.naturalHeight });
        }}
      />
    </span>
  );
}

export function StoragePreview({ file, loading = false, previewUrl, previewText, previewTable }: { file: StorageFile; loading?: boolean; previewUrl: string; previewText: string; previewTable?: PreviewTablePayload }) {
  if (loading) return <FileTypeFallback file={file} loading />;
  if (canTablePreview(file)) return <SpreadsheetPreview table={previewTable} />;
  if (file.preview_kind === 'image' && previewUrl) return <img src={previewUrl} alt={file.name} />;
  if (file.preview_kind === 'video' && previewUrl) return <video src={previewUrl} controls />;
  if (file.preview_kind === 'audio' && previewUrl) return <audio src={previewUrl} controls />;
  if (['pdf', 'document', 'presentation', 'spreadsheet'].includes(file.preview_kind) && previewUrl) {
    return <iframe className="document-render-frame" src={previewUrl} title={file.name} />;
  }
  if (file.preview_kind === 'markdown') return <MarkdownPreview text={previewText} />;
  if (file.preview_kind === 'text') return <pre>{previewText}</pre>;
  if (['document', 'presentation', 'spreadsheet'].includes(file.preview_kind) && previewText) return <pre>{previewText}</pre>;
  return (
    <div className="format-preview">
      <Icon name={iconForKind(file.preview_kind)} />
      <strong>{kindLabels[file.preview_kind]}</strong>
      <p>{file.name}</p>
      <small>Preview metadata is available. Download this file to open it with the native editor or viewer.</small>
    </div>
  );
}

export function FileCardPreview({ file }: { file: StorageFile }) {
  const [previewUrl, setPreviewUrl] = useState('');
  const [previewFailed, setPreviewFailed] = useState(false);
  const [previewLoading, setPreviewLoading] = useState(false);

  useEffect(() => {
    setPreviewUrl('');
    setPreviewFailed(false);
    const canLoadAssetPreview = canCardAssetPreview(file);
    setPreviewLoading(canLoadAssetPreview);
    if (!canLoadAssetPreview) return;
    let active = true;
    loadCardPreview(file)
      .then((payload) => {
        if (!active) return;
        setPreviewUrl(payload.url);
      })
      .catch(() => {
        if (active) setPreviewFailed(true);
      })
      .finally(() => {
        if (active) setPreviewLoading(false);
    });
    return () => {
      active = false;
    };
  }, [file]);

  if (previewFailed || !canCardAssetPreview(file)) {
    return <FileTypeFallback file={file} />;
  }
  if (file.preview_kind === 'image' && previewUrl) {
    return <CardImagePreview src={previewUrl} />;
  }
  if (file.preview_kind === 'video' && previewUrl) {
    return <video src={previewUrl} muted playsInline preload="metadata" />;
  }
  return <FileTypeFallback file={file} loading={previewLoading} />;
}
