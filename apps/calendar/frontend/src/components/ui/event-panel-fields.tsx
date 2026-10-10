import {
  cloneElement,
  isValidElement,
  useId,
  type ReactElement,
  type ReactNode,
} from "react";
import { Label } from "./label";
import { Input } from "./input";
import { parseZonedInput, zonedInput } from "./time-layout";
import { t } from "@/preferences";
export function Field({
  label,
  children,
}: {
  label: string;
  children: ReactNode;
}) {
  const id = useId();
  return (
    <div className="calendar-event-panel__field">
      <Label htmlFor={id}>{t(label)}</Label>
      {isValidElement(children)
        ? cloneElement(
            children as ReactElement<{ id?: string; "aria-label"?: string }>,
            { id, "aria-label": t(label) },
          )
        : children}
    </div>
  );
}
export function DateTimeField({
  label,
  value,
  zone,
  allDay,
  disabled,
  onChange,
}: {
  label: string;
  value?: Date;
  zone: string;
  allDay?: boolean;
  disabled?: boolean;
  onChange: (value: Date) => void;
}) {
  return (
    <Field label={label}>
      <Input
        type={allDay ? "date" : "datetime-local"}
        step={allDay ? undefined : 900}
        value={zonedInput(value, zone, allDay)}
        disabled={disabled}
        onChange={(event) =>
          onChange(parseZonedInput(event.target.value, zone))
        }
      />
    </Field>
  );
}
