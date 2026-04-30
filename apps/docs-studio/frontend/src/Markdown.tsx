import { useState } from 'react';
import type { ReactElement, ReactNode } from 'react';

interface MarkdownProps {
  markdown: string;
}

function renderInline(text: string): ReactNode[] {
  const nodes: ReactNode[] = [];
  const pattern = /(`[^`]+`|\*\*[^*]+\*\*)/g;
  let lastIndex = 0;
  let match: RegExpExecArray | null;
  while ((match = pattern.exec(text)) !== null) {
    if (match.index > lastIndex) {
      nodes.push(text.slice(lastIndex, match.index));
    }
    const value = match[0];
    if (value.startsWith('`')) {
      nodes.push(<code key={`${value}-${match.index}`}>{value.slice(1, -1)}</code>);
    } else {
      nodes.push(<strong key={`${value}-${match.index}`}>{value.slice(2, -2)}</strong>);
    }
    lastIndex = match.index + value.length;
  }
  if (lastIndex < text.length) {
    nodes.push(text.slice(lastIndex));
  }
  return nodes;
}

function isTableSeparator(line: string) {
  return /^\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)+\|?$/.test(line);
}

function parseTableRow(line: string) {
  return line
    .trim()
    .replace(/^\|/, '')
    .replace(/\|$/, '')
    .split('|')
    .map((cell) => cell.trim());
}

function renderTable(lines: string[], key: string) {
  const [head, , ...body] = lines;
  return (
    <div className="md-table-wrap" key={key}>
      <table>
        <thead>
          <tr>{parseTableRow(head).map((cell) => <th key={cell}>{renderInline(cell)}</th>)}</tr>
        </thead>
        <tbody>
          {body.map((row, rowIndex) => (
            <tr key={`${key}-${rowIndex}`}>
              {parseTableRow(row).map((cell, cellIndex) => <td key={`${cell}-${cellIndex}`}>{renderInline(cell)}</td>)}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function parseDetailsSummary(summary: string): { label: string; count: string | null } {
  const match = summary.match(/^(.*)\s+\((\d+)\)$/);
  if (!match) {
    return { label: summary, count: null };
  }
  return { label: match[1], count: match[2] };
}

function MarkdownDetails({ summary, markdown }: { summary: string; markdown: string }) {
  const [open, setOpen] = useState(false);
  const parsedSummary = parseDetailsSummary(summary);
  return (
    <div className={`md-details ${open ? 'open' : ''}`}>
      <button className="md-details-summary" type="button" aria-expanded={open} onClick={() => setOpen((current) => !current)}>
        <span className="md-details-title">
          <span>{renderInline(parsedSummary.label)}</span>
          {parsedSummary.count !== null ? <span className="md-details-count">{parsedSummary.count}</span> : null}
        </span>
        <span className="md-details-mark" aria-hidden="true">{open ? '-' : '+'}</span>
      </button>
      <div className="md-details-body" aria-hidden={!open}>
        <div className="md-details-content">
          <Markdown markdown={markdown} />
        </div>
      </div>
    </div>
  );
}

export function Markdown({ markdown }: MarkdownProps) {
  const elements: ReactElement[] = [];
  const lines = markdown.split('\n');
  let index = 0;

  const paragraph: string[] = [];
  const list: Array<{ text: string; checked?: boolean; ordered?: boolean }> = [];

  const flushParagraph = () => {
    if (!paragraph.length) {
      return;
    }
    elements.push(<p key={`p-${elements.length}`}>{renderInline(paragraph.join(' '))}</p>);
    paragraph.length = 0;
  };

  const flushList = () => {
    if (!list.length) {
      return;
    }
    const ordered = list.some((item) => item.ordered);
    const children = list.map((item, itemIndex) => (
      <li className={item.checked !== undefined ? 'task-item' : undefined} key={`${item.text}-${itemIndex}`}>
        {item.checked !== undefined ? <input type="checkbox" checked={item.checked} readOnly /> : null}
        <span>{renderInline(item.text)}</span>
      </li>
    ));
    elements.push(ordered ? <ol key={`ol-${elements.length}`}>{children}</ol> : <ul key={`ul-${elements.length}`}>{children}</ul>);
    list.length = 0;
  };

  const flushAll = () => {
    flushParagraph();
    flushList();
  };

  while (index < lines.length) {
    const line = lines[index];
    const trimmed = line.trim();

    if (!trimmed) {
      flushAll();
      index += 1;
      continue;
    }

    if (trimmed.startsWith('```')) {
      flushAll();
      const code: string[] = [];
      index += 1;
      while (index < lines.length && !lines[index].trim().startsWith('```')) {
        code.push(lines[index]);
        index += 1;
      }
      elements.push(<pre key={`pre-${elements.length}`}><code>{code.join('\n')}</code></pre>);
      index += 1;
      continue;
    }

    if (trimmed === '<details>') {
      flushAll();
      let summary = 'Details';
      const details: string[] = [];
      index += 1;
      if (index < lines.length) {
        const summaryMatch = lines[index].trim().match(/^<summary>(.+)<\/summary>$/);
        if (summaryMatch) {
          summary = summaryMatch[1];
          index += 1;
        }
      }
      while (index < lines.length && lines[index].trim() !== '</details>') {
        details.push(lines[index]);
        index += 1;
      }
      elements.push(
        <MarkdownDetails
          key={`details-${elements.length}`}
          summary={summary}
          markdown={details.join('\n')}
        />
      );
      index += 1;
      continue;
    }

    if (trimmed.includes('|') && index + 1 < lines.length && isTableSeparator(lines[index + 1])) {
      flushAll();
      const tableLines = [trimmed, lines[index + 1].trim()];
      index += 2;
      while (index < lines.length && lines[index].trim().includes('|')) {
        tableLines.push(lines[index].trim());
        index += 1;
      }
      elements.push(renderTable(tableLines, `table-${elements.length}`));
      continue;
    }

    if (trimmed === '---') {
      flushAll();
      elements.push(<hr key={`hr-${elements.length}`} />);
      index += 1;
      continue;
    }

    if (trimmed.startsWith('> ')) {
      flushAll();
      const quote: string[] = [];
      while (index < lines.length && lines[index].trim().startsWith('> ')) {
        quote.push(lines[index].trim().slice(2));
        index += 1;
      }
      elements.push(<blockquote key={`quote-${elements.length}`}>{quote.map((item, quoteIndex) => <p key={`${item}-${quoteIndex}`}>{renderInline(item)}</p>)}</blockquote>);
      continue;
    }

    if (trimmed.startsWith('### ')) {
      flushAll();
      elements.push(<h3 key={`h3-${elements.length}`}>{renderInline(trimmed.slice(4))}</h3>);
      index += 1;
      continue;
    }

    if (trimmed.startsWith('## ')) {
      flushAll();
      elements.push(<h2 key={`h2-${elements.length}`}>{renderInline(trimmed.slice(3))}</h2>);
      index += 1;
      continue;
    }

    if (trimmed.startsWith('# ')) {
      flushAll();
      index += 1;
      continue;
    }

    const taskMatch = trimmed.match(/^- \[(x| )\]\s+(.+)$/i);
    if (taskMatch) {
      flushParagraph();
      list.push({ text: taskMatch[2], checked: taskMatch[1].toLowerCase() === 'x' });
      index += 1;
      continue;
    }

    const bulletMatch = trimmed.match(/^- (.+)$/);
    if (bulletMatch) {
      flushParagraph();
      list.push({ text: bulletMatch[1] });
      index += 1;
      continue;
    }

    const orderedMatch = trimmed.match(/^\d+\.\s+(.+)$/);
    if (orderedMatch) {
      flushParagraph();
      list.push({ text: orderedMatch[1], ordered: true });
      index += 1;
      continue;
    }

    flushList();
    paragraph.push(trimmed);
    index += 1;
  }

  flushAll();
  return <>{elements}</>;
}
