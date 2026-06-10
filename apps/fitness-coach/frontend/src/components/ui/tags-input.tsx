import { useId, useRef, useState } from 'react';
import { Eraser, X } from 'lucide-react';

type BasicProps = {
  label?: string;
  value: string[];
  onValueChange: (value: string[]) => void;
  placeholder?: string;
  maxTags?: number;
};

function cleanTags(values: string[], maxTags = 24) {
  const next: string[] = [];
  values.forEach((value) => {
    value
      .split(',')
      .map((item) => item.trim().toLowerCase())
      .filter(Boolean)
      .forEach((tag) => {
        if (!next.includes(tag) && next.length < maxTags) next.push(tag);
      });
  });
  return next;
}

export const Basic = ({
  label = 'Tags',
  value,
  onValueChange,
  placeholder = 'Add tags and press enter',
  maxTags = 24
}: BasicProps) => {
  const inputId = useId();
  const inputRef = useRef<HTMLInputElement | null>(null);
  const [draft, setDraft] = useState('');
  const tags = cleanTags(value, maxTags);

  function commit(values: string[]) {
    const next = cleanTags([...tags, ...values], maxTags);
    onValueChange(next);
    setDraft('');
  }

  function removeTag(tag: string) {
    onValueChange(tags.filter((item) => item !== tag));
  }

  return (
    <div className="maverick-tags-input-wrap">
      <div className="maverick-tags-input">
        <label className="maverick-tags-label" htmlFor={inputId}>
          {label}
        </label>
        <div className="maverick-tags-control" onClick={() => inputRef.current?.focus()}>
          {tags.map((itemValue) => (
            <span key={itemValue} className="maverick-tags-item">
              <span className="maverick-tags-item-preview">
                <span>{itemValue}</span>
                <button className="maverick-tags-item-delete" type="button" aria-label={`Remove ${itemValue}`} onClick={() => removeTag(itemValue)}>
                  <X size={12} aria-hidden="true" />
                </button>
              </span>
            </span>
          ))}
          <input
            id={inputId}
            ref={inputRef}
            value={draft}
            placeholder={tags.length >= maxTags ? '' : placeholder}
            className="maverick-tags-text-input"
            disabled={tags.length >= maxTags}
            onBlur={() => {
              if (draft.trim()) commit([draft]);
            }}
            onChange={(event) => setDraft(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === 'Enter' || event.key === ',') {
                event.preventDefault();
                if (draft.trim()) commit([draft]);
              }
              if (event.key === 'Backspace' && !draft && tags.length) {
                onValueChange(tags.slice(0, -1));
              }
            }}
            onPaste={(event) => {
              const text = event.clipboardData.getData('text');
              if (!text.includes(',')) return;
              event.preventDefault();
              commit([text]);
            }}
          />
        </div>
        {tags.length ? (
          <button className="maverick-tags-clear" type="button" onClick={() => onValueChange([])}>
            <Eraser size={14} aria-hidden="true" />
            <span>Clear all</span>
          </button>
        ) : null}
      </div>
    </div>
  );
};

export const TagsInputField = Basic;
