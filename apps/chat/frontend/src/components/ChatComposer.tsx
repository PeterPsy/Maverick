import { FormEvent } from "react";

export function ChatComposer({
  disabled,
  isSending,
  onChange,
  onSubmit,
  value,
}: {
  disabled: boolean;
  isSending: boolean;
  onChange: (value: string) => void;
  onSubmit: () => void;
  value: string;
}) {
  function submit(event: FormEvent) {
    event.preventDefault();
    onSubmit();
  }

  return (
    <section className="chat-ui-surface chatapp-composer">
      <form className="chatapp-form-stack" onSubmit={submit}>
        <div className={`chatapp-composer__row ${isSending ? "is-busy" : "is-idle"}`}>
          <button
            aria-label="Aggiungi allegati"
            className="chatapp-attachment-picker__trigger"
            disabled
            title="Allegati non ancora abilitati in v3"
            type="button"
          >
            +
          </button>
          <textarea
            className="chat-ui-input chat-ui-input--textarea chatapp-composer__field"
            disabled={disabled}
            onChange={(event) => onChange(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter" && !event.shiftKey && !event.altKey) {
                event.preventDefault();
                onSubmit();
              }
            }}
            placeholder="Fai una domanda"
            rows={3}
            value={value}
          />
          <div className="chatapp-composer__actions">
            <button
              aria-label="Invia messaggio"
              className="chatapp-composer__icon-action is-send"
              disabled={disabled || isSending || !value.trim()}
              title="Invia"
              type="submit"
            >
              {isSending ? (
                <span className="chat-ui-button__spinner" />
              ) : (
                <span aria-hidden="true" className="chatapp-send-glyph">
                  &gt;
                </span>
              )}
            </button>
          </div>
        </div>
        <div className={`chatapp-composer__status ${isSending ? "" : "is-connected"}`} aria-live="polite">
          {isSending ? "Runtime al lavoro" : "Runtime collegato correttamente"}
        </div>
      </form>
    </section>
  );
}
