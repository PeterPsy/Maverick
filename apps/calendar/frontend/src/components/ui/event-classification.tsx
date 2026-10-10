import { useState } from "react";
import { t } from "@/preferences";
import { Field } from "./event-panel-fields";
import type { Event } from "./calendar-types";
import type { EventPanelProps } from "./event-panel-types";
export function EventClassification(
  props: EventPanelProps & { draft: NonNullable<EventPanelProps["draft"]> },
) {
  const draft = props.draft;
  const [tag, setTag] = useState("");
  const tags = Array.from(
    new Set([...props.availableTags, ...(draft.tags || [])]),
  );
  return (
    <details>
      <summary>{t("Classification and availability")}</summary>
      <div className="calendar-editor-grid">
        <Field label="Busy">
          <select
            value={draft.transparency || "opaque"}
            onChange={(e) =>
              props.setDraft({
                transparency: e.target.value as Event["transparency"],
              })
            }
          >
            <option value="opaque">{t("Busy")}</option>
            <option value="transparent">{t("Free")}</option>
          </select>
        </Field>
        <Field label="Status">
          <select
            value={draft.status || "confirmed"}
            onChange={(e) =>
              props.setDraft({
                status: e.target.value as Event["status"],
              })
            }
          >
            {["confirmed", "tentative", "cancelled"].map((s) => (
              <option key={s} value={s}>
                {t(s[0].toUpperCase() + s.slice(1))}
              </option>
            ))}
          </select>
        </Field>
      </div>
      <div className="calendar-editor-grid">
        <Field label="Category">
          <select
            value={draft.category || props.categories[0]}
            onChange={(e) => props.setDraft({ category: e.target.value })}
          >
            {Array.from(
              new Set([...props.categories, draft.category || "Meeting"]),
            ).map((category) => (
              <option key={category} value={category}>
                {t(category)}
              </option>
            ))}
          </select>
        </Field>
        <Field label="Color">
          <select
            value={draft.color || "blue"}
            onChange={(e) => props.setDraft({ color: e.target.value })}
          >
            {props.colors.map((color) => (
              <option key={color.value} value={color.value}>
                {t(color.name)}
              </option>
            ))}
          </select>
        </Field>
      </div>
      <fieldset className="calendar-tag-editor">
        <legend>{t("Tags")}</legend>
        <div>
          {tags.map((value) => (
            <button
              type="button"
              key={value}
              aria-pressed={draft.tags?.includes(value) || false}
              onClick={() => props.toggleTag(value)}
            >
              {value}
            </button>
          ))}
        </div>
        <Field label="New tag">
          <input
            value={tag}
            maxLength={120}
            onChange={(e) => setTag(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") {
                e.preventDefault();
                if (tag.trim() && !draft.tags?.includes(tag.trim()))
                  props.toggleTag(tag.trim());
                setTag("");
              }
            }}
          />
        </Field>
        <button
          type="button"
          disabled={!tag.trim()}
          onClick={() => {
            if (!draft.tags?.includes(tag.trim())) props.toggleTag(tag.trim());
            setTag("");
          }}
        >
          {t("Add tag")}
        </button>
      </fieldset>
    </details>
  );
}
