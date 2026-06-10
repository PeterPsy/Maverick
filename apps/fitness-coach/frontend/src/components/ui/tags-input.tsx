"use client";

import {
  TagsInputClearTrigger,
  TagsInputContext,
  TagsInputControl,
  TagsInputHiddenInput,
  TagsInputInput,
  TagsInputItem,
  TagsInputItemDeleteTrigger,
  TagsInputItemInput,
  TagsInputItemPreview,
  TagsInputItemText,
  TagsInputLabel,
  TagsInputRoot,
  type TagsInputValueChangeDetails,
  type UseTagsInputContext
} from '@ark-ui/react';
import { Eraser, X } from 'lucide-react';

const TagsInput = {
  Root: TagsInputRoot,
  Context: TagsInputContext,
  Label: TagsInputLabel,
  Control: TagsInputControl,
  Item: TagsInputItem,
  ItemPreview: TagsInputItemPreview,
  ItemText: TagsInputItemText,
  ItemDeleteTrigger: TagsInputItemDeleteTrigger,
  ItemInput: TagsInputItemInput,
  Input: TagsInputInput,
  ClearTrigger: TagsInputClearTrigger,
  HiddenInput: TagsInputHiddenInput
};

type BasicProps = {
  label?: string;
  value: string[];
  onValueChange: (value: string[]) => void;
  placeholder?: string;
  maxTags?: number;
};

function cleanTags(values: string[]) {
  const next: string[] = [];
  values.forEach((value) => {
    const tag = value.trim().toLowerCase();
    if (tag && !next.includes(tag)) next.push(tag);
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
  return (
    <div className="maverick-tags-input-wrap">
      <TagsInput.Root
        className="maverick-tags-input"
        value={value}
        max={maxTags}
        addOnPaste
        blurBehavior="add"
        sanitizeValue={(nextValue: string) => nextValue.trim().toLowerCase()}
        onValueChange={(details: TagsInputValueChangeDetails) => onValueChange(cleanTags(details.value))}
      >
        <TagsInput.Context>
          {(tagsInput: UseTagsInputContext) => (
            <>
              <TagsInput.Label className="maverick-tags-label">
                {label}
              </TagsInput.Label>

              <TagsInput.Control className="maverick-tags-control">
                {tagsInput.value.map((itemValue: string, index: number) => (
                  <TagsInput.Item
                    key={`${itemValue}-${index}`}
                    index={index}
                    value={itemValue}
                    className="maverick-tags-item"
                  >
                    <TagsInput.ItemPreview className="maverick-tags-item-preview">
                      <TagsInput.ItemText>{itemValue}</TagsInput.ItemText>
                      <TagsInput.ItemDeleteTrigger className="maverick-tags-item-delete" aria-label={`Remove ${itemValue}`}>
                        <X size={12} aria-hidden="true" />
                      </TagsInput.ItemDeleteTrigger>
                    </TagsInput.ItemPreview>
                    <TagsInput.ItemInput className="maverick-tags-item-input" />
                  </TagsInput.Item>
                ))}

                <TagsInput.Input
                  placeholder={placeholder}
                  className="maverick-tags-text-input"
                />
              </TagsInput.Control>

              {tagsInput.value.length ? (
                <TagsInput.ClearTrigger className="maverick-tags-clear">
                  <Eraser size={14} aria-hidden="true" />
                  <span>Clear all</span>
                </TagsInput.ClearTrigger>
              ) : null}
            </>
          )}
        </TagsInput.Context>

        <TagsInput.HiddenInput />
      </TagsInput.Root>
    </div>
  );
};

export const TagsInputField = Basic;
