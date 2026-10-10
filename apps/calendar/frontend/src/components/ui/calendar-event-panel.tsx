import { useEffect, useState } from "react";
import { X } from "lucide-react";
import { Button } from "./button";
import { EventDetails } from "./event-details";
import { EventEditor } from "./event-editor";
import { eventIsReadOnly } from "./calendar-utils";
import type { Event } from "./calendar-types";
import type { EventPanelProps } from "./event-panel-types";
import { t } from "@/preferences";

export function EventPanel(props: EventPanelProps) {
  const creating = props.mode === "create",
    draft = props.draft;
  const [editing, setEditing] = useState(creating);
  useEffect(() => {
    setEditing(creating);
  }, [creating, draft?.id]);
  const readOnly =
    !creating && !!draft && eventIsReadOnly(draft, props.calendars || []);
  const showingEditor = creating || (editing && !readOnly);
  return (
    <section
      className="calendar-event-panel"
      aria-label={t(creating ? "Create Event" : "Event Details")}
    >
      <header className="calendar-event-panel__header">
        <span>
          {t(
            creating
              ? "Create Event"
              : showingEditor
                ? "Edit event"
                : "Event Details",
          )}
        </span>
        <button
          type="button"
          disabled={props.isSaving}
          onClick={props.onClose}
          aria-label={t("Close")}
        >
          <X size={18} aria-hidden="true" />
        </button>
      </header>
      {props.error && (
        <div role="alert" className="calendar-event-panel__error">
          {props.error}
        </div>
      )}
      {!draft ? (
        <p>{t("Loading calendar…")}</p>
      ) : showingEditor ? (
        <EventEditor {...props} draft={draft} />
      ) : (
        <EventDetails
          event={draft as Event}
          connections={props.connections || []}
          calendars={props.calendars || []}
          readOnly={readOnly}
        />
      )}
      <footer className="calendar-event-panel__footer">
        {showingEditor ? (
          <>
            <Button
              className="calendar-event-panel__save"
              disabled={
                props.isSaving ||
                !draft ||
                !props.canSave ||
                (!creating && props.hasChanges === false)
              }
              onClick={creating ? props.onCreate : props.onUpdate}
            >
              {t(props.isSaving ? "Saving..." : "Save")}
            </Button>
            {!creating && (
              <Button
                variant="secondary"
                disabled={props.isSaving}
                onClick={() => {
                  props.onCancelEdit?.();
                  setEditing(false);
                }}
              >
                {t("Cancel edit")}
              </Button>
            )}
          </>
        ) : (
          !readOnly && (
            <Button
              className="calendar-event-panel__save"
              disabled={!props.canSave || props.isSaving}
              onClick={() => setEditing(true)}
            >
              {t("Edit event")}
            </Button>
          )
        )}
        {!creating && !showingEditor && !readOnly && (
          <Button
            variant="secondary"
            className="calendar-event-panel__delete"
            disabled={props.isSaving || !props.canSave}
            onClick={props.onDelete}
          >
            {t("Delete")}
          </Button>
        )}
        <Button
          variant="secondary"
          disabled={props.isSaving}
          onClick={props.onClose}
        >
          {t("Close")}
        </Button>
      </footer>
    </section>
  );
}
