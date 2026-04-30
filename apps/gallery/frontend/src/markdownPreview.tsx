import type { ReactNode } from 'react';

type TableBlock = {
  alignments: Array<'left' | 'center' | 'right'>;
  headers: string[];
  rows: string[][];
};

function isFence(line: string) {
  return line.trim().startsWith('```');
}

function isHeading(line: string) {
  return /^#{1,6}\s+\S/.test(line.trim());
}

function isQuote(line: string) {
  return line.trim().startsWith('>');
}

function isListItem(line: string) {
  return /^\s*[-*+]\s+\S/.test(line) || /^\s*\d+\.\s+\S/.test(line);
}

function isTableSeparator(line: string) {
  const cells = splitTableRow(line);
  return cells.length > 0 && cells.every((cell) => /^:?-{3,}:?$/.test(cell.trim()));
}

function splitTableRow(line: string) {
  const trimmed = line.trim().replace(/^\|/, '').replace(/\|$/, '');
  if (!trimmed.includes('|')) return [];
  return trimmed.split('|').map((cell) => cell.trim());
}

function tableFrom(lines: string[], start: number): { table: TableBlock; nextIndex: number } | null {
  if (start + 1 >= lines.length || !lines[start].includes('|') || !isTableSeparator(lines[start + 1])) return null;
  const headers = splitTableRow(lines[start]);
  const separators = splitTableRow(lines[start + 1]);
  if (!headers.length || headers.length !== separators.length) return null;

  const alignments = separators.map((cell) => {
    const value = cell.trim();
    if (value.startsWith(':') && value.endsWith(':')) return 'center';
    if (value.endsWith(':')) return 'right';
    return 'left';
  });
  const rows: string[][] = [];
  let cursor = start + 2;
  while (cursor < lines.length && lines[cursor].includes('|') && splitTableRow(lines[cursor]).length) {
    const row = splitTableRow(lines[cursor]);
    rows.push(headers.map((_header, index) => row[index] || ''));
    cursor += 1;
  }
  return { table: { alignments, headers, rows }, nextIndex: cursor };
}

function safeHref(href: string) {
  const trimmed = href.trim();
  if (/^(https?:|mailto:|#|\/)/i.test(trimmed)) return trimmed;
  return '';
}

function renderInline(text: string): ReactNode[] {
  const nodes: ReactNode[] = [];
  let cursor = 0;

  while (cursor < text.length) {
    const codeStart = text.indexOf('`', cursor);
    const linkStart = text.indexOf('[', cursor);
    const strongStart = text.indexOf('**', cursor);
    const emStart = text.indexOf('*', cursor);
    const candidates = [codeStart, linkStart, strongStart, emStart].filter((index) => index >= 0);
    const next = candidates.length ? Math.min(...candidates) : -1;

    if (next < 0) {
      nodes.push(text.slice(cursor));
      break;
    }
    if (next > cursor) nodes.push(text.slice(cursor, next));

    if (next === codeStart) {
      const end = text.indexOf('`', next + 1);
      if (end < 0) {
        nodes.push(text.slice(next));
        break;
      }
      nodes.push(<code key={`code-${next}`}>{text.slice(next + 1, end)}</code>);
      cursor = end + 1;
      continue;
    }

    if (next === linkStart) {
      const labelEnd = text.indexOf(']', next + 1);
      const hrefStart = labelEnd >= 0 && text[labelEnd + 1] === '(' ? labelEnd + 2 : -1;
      const hrefEnd = hrefStart >= 0 ? text.indexOf(')', hrefStart) : -1;
      if (labelEnd < 0 || hrefStart < 0 || hrefEnd < 0) {
        nodes.push(text[next]);
        cursor = next + 1;
        continue;
      }
      const href = safeHref(text.slice(hrefStart, hrefEnd));
      const label = text.slice(next + 1, labelEnd);
      nodes.push(href ? <a key={`link-${next}`} href={href} target="_blank" rel="noreferrer">{label}</a> : label);
      cursor = hrefEnd + 1;
      continue;
    }

    if (next === strongStart) {
      const end = text.indexOf('**', next + 2);
      if (end < 0) {
        nodes.push(text.slice(next, next + 2));
        cursor = next + 2;
        continue;
      }
      nodes.push(<strong key={`strong-${next}`}>{renderInline(text.slice(next + 2, end))}</strong>);
      cursor = end + 2;
      continue;
    }

    const end = text.indexOf('*', next + 1);
    if (end < 0) {
      nodes.push(text[next]);
      cursor = next + 1;
      continue;
    }
    nodes.push(<em key={`em-${next}`}>{renderInline(text.slice(next + 1, end))}</em>);
    cursor = end + 1;
  }

  return nodes;
}

export function MarkdownPreview({ text, compact = false }: { text: string; compact?: boolean }) {
  const lines = text.split(/\r?\n/);
  const blocks: ReactNode[] = [];
  let cursor = 0;

  while (cursor < lines.length) {
    const line = lines[cursor];
    if (!line.trim()) {
      cursor += 1;
      continue;
    }

    if (isFence(line)) {
      const code: string[] = [];
      cursor += 1;
      while (cursor < lines.length && !isFence(lines[cursor])) {
        code.push(lines[cursor]);
        cursor += 1;
      }
      if (cursor < lines.length) cursor += 1;
      blocks.push(<pre key={`code-${cursor}`}><code>{code.join('\n')}</code></pre>);
      continue;
    }

    const table = tableFrom(lines, cursor);
    if (table) {
      blocks.push(
        <div className="markdown-table-wrap" key={`table-${cursor}`}>
          <table>
            <thead>
              <tr>
                {table.table.headers.map((header, index) => (
                  <th key={`${header}-${index}`} style={{ textAlign: table.table.alignments[index] }}>{renderInline(header)}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {table.table.rows.map((row, rowIndex) => (
                <tr key={`row-${rowIndex}`}>
                  {row.map((cell, cellIndex) => (
                    <td key={`${rowIndex}-${cellIndex}`} style={{ textAlign: table.table.alignments[cellIndex] }}>{renderInline(cell)}</td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      );
      cursor = table.nextIndex;
      continue;
    }

    if (isHeading(line)) {
      const match = /^(#{1,6})\s+(.+)$/.exec(line.trim());
      const level = Math.min(match?.[1].length || 1, compact ? 4 : 3);
      const children = renderInline(match?.[2] || '');
      if (level === 1) blocks.push(<h1 key={`heading-${cursor}`}>{children}</h1>);
      else if (level === 2) blocks.push(<h2 key={`heading-${cursor}`}>{children}</h2>);
      else if (level === 3) blocks.push(<h3 key={`heading-${cursor}`}>{children}</h3>);
      else blocks.push(<h4 key={`heading-${cursor}`}>{children}</h4>);
      cursor += 1;
      continue;
    }

    if (isQuote(line)) {
      const quoteLines: string[] = [];
      while (cursor < lines.length && isQuote(lines[cursor])) {
        quoteLines.push(lines[cursor].trim().replace(/^>\s?/, ''));
        cursor += 1;
      }
      blocks.push(<blockquote key={`quote-${cursor}`}>{quoteLines.map((item, index) => <p key={index}>{renderInline(item)}</p>)}</blockquote>);
      continue;
    }

    if (isListItem(line)) {
      const ordered = /^\s*\d+\.\s+\S/.test(line);
      const items: string[] = [];
      while (cursor < lines.length && isListItem(lines[cursor]) && /^\s*\d+\.\s+\S/.test(lines[cursor]) === ordered) {
        items.push(lines[cursor].replace(/^\s*(?:[-*+]|\d+\.)\s+/, ''));
        cursor += 1;
      }
      const ListTag = ordered ? 'ol' : 'ul';
      blocks.push(<ListTag key={`list-${cursor}`}>{items.map((item, index) => <li key={index}>{renderInline(item)}</li>)}</ListTag>);
      continue;
    }

    const paragraph: string[] = [line.trim()];
    cursor += 1;
    while (
      cursor < lines.length
      && lines[cursor].trim()
      && !isFence(lines[cursor])
      && !isHeading(lines[cursor])
      && !isQuote(lines[cursor])
      && !isListItem(lines[cursor])
      && !tableFrom(lines, cursor)
    ) {
      paragraph.push(lines[cursor].trim());
      cursor += 1;
    }
    blocks.push(<p key={`p-${cursor}`}>{renderInline(paragraph.join(' '))}</p>);
  }

  return <article className={compact ? 'markdown-preview compact' : 'markdown-preview'}>{blocks}</article>;
}
