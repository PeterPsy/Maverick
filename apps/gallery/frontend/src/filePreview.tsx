import { useEffect, useState } from 'react';
import { iconForKind, kindLabels } from './galleryMeta';
import { Icon } from './Icon';
import { MarkdownPreview } from './markdownPreview';
import { loadCardPreview } from './previewCache';
import type { GalleryFile, PreviewTablePayload, TablePreviewSheet } from './types';

export function canTextPreview(file: GalleryFile) {
  return ['text', 'markdown'].includes(file.preview_kind);
}

export function canTablePreview(file: GalleryFile) {
  return file.preview_kind === 'spreadsheet' || file.extension.toLowerCase() === '.csv';
}

export function canInlinePreview(file: GalleryFile) {
  return ['image', 'video', 'audio', 'text', 'markdown', 'pdf', 'document', 'presentation', 'spreadsheet'].includes(file.preview_kind);
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
        <strong>{table ? 'No tabular preview available' : 'Loading table preview...'}</strong>
      </div>
    );
  }
  return (
    <div className={compact ? 'spreadsheet-preview compact' : 'spreadsheet-preview'}>
      {sheets.map((sheet) => <SpreadsheetSheet key={sheet.name} sheet={sheet} compact={compact} />)}
    </div>
  );
}

function FileTypeFallback({ file }: { file: GalleryFile }) {
  return (
    <div className="file-type-preview">
      <Icon name={iconForKind(file.preview_kind)} className="gallery-card-icon" />
      <strong>{file.extension ? file.extension.replace('.', '').toUpperCase() : kindLabels[file.preview_kind]}</strong>
    </div>
  );
}

export function GalleryPreview({ file, previewUrl, previewText, previewTable }: { file: GalleryFile; previewUrl: string; previewText: string; previewTable?: PreviewTablePayload }) {
  if (canTablePreview(file)) return <SpreadsheetPreview table={previewTable} />;
  if (file.preview_kind === 'image' && previewUrl) return <img src={previewUrl} alt={file.name} />;
  if (file.preview_kind === 'video' && previewUrl) return <video src={previewUrl} controls />;
  if (file.preview_kind === 'audio' && previewUrl) return <audio src={previewUrl} controls />;
  if (['pdf', 'document', 'presentation', 'spreadsheet'].includes(file.preview_kind) && previewUrl) {
    return <iframe className="document-render-frame" src={previewUrl} title={file.name} />;
  }
  if (file.preview_kind === 'markdown') return previewText ? <MarkdownPreview text={previewText} /> : <pre>Loading preview...</pre>;
  if (file.preview_kind === 'text') return <pre>{previewText || 'Loading preview...'}</pre>;
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

export function FileCardPreview({ file }: { file: GalleryFile }) {
  const [previewUrl, setPreviewUrl] = useState('');
  const [previewText, setPreviewText] = useState('');
  const [previewTable, setPreviewTable] = useState<PreviewTablePayload | undefined>(undefined);
  const [previewFailed, setPreviewFailed] = useState(false);

  useEffect(() => {
    setPreviewUrl('');
    setPreviewText('');
    setPreviewTable(undefined);
    setPreviewFailed(false);
    if (!canInlinePreview(file) && !canTextPreview(file)) return;
    let active = true;
    loadCardPreview(file)
      .then((payload) => {
        if (!active) return;
        setPreviewText(payload.text);
        setPreviewUrl(payload.url);
        setPreviewTable(payload.table);
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
  if (canTablePreview(file)) {
    return <SpreadsheetPreview table={previewTable} compact />;
  }
  if (['pdf', 'document', 'presentation', 'spreadsheet'].includes(file.preview_kind) && previewUrl) {
    if (['document', 'presentation', 'spreadsheet'].includes(file.preview_kind)) {
      return <img className="document-card-image" src={previewUrl} alt="" loading="lazy" />;
    }
    return <iframe className="document-card-frame" src={`${previewUrl}#toolbar=0&navpanes=0&scrollbar=0`} title={`${file.name} preview`} tabIndex={-1} />;
  }
  if (file.preview_kind === 'markdown') {
    return previewText ? <MarkdownPreview text={previewText} compact /> : <FileTypeFallback file={file} />;
  }
  if (file.preview_kind === 'text') {
    return previewText ? <pre>{previewText}</pre> : <FileTypeFallback file={file} />;
  }
  if (['document', 'presentation', 'spreadsheet'].includes(file.preview_kind) && previewText) {
    return <pre>{previewText}</pre>;
  }
  return <FileTypeFallback file={file} />;
}
