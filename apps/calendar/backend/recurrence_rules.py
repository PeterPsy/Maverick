"""iCalendar rule parsing and lossless partitioning at a series boundary."""

from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo
from dateutil.rrule import rruleset, rrulestr
from time_values import iso_time

MAX_OCCURRENCES = 10000


def recurrence_rules(value):
    if not value:
        return []
    rules = value.get("rules")
    if rules is not None:
        if not isinstance(rules, list) or not all(
            isinstance(rule, str) for rule in rules
        ):
            raise ValueError("Recurrence rules must be a list of iCalendar strings.")
        return rules
    frequency = str(value.get("frequency") or "").upper()
    if frequency not in {"DAILY", "WEEKLY", "MONTHLY", "YEARLY"}:
        if set(value) <= {"exceptions", "until"}:
            return []
        raise ValueError(
            "Recurrence requires rules or a daily, weekly, monthly or yearly frequency."
        )
    rule = f"RRULE:FREQ={frequency}"
    for field in ("interval", "count"):
        if field in value:
            number = value[field]
            if (
                not isinstance(number, int)
                or isinstance(number, bool)
                or not 1 <= number <= MAX_OCCURRENCES
            ):
                raise ValueError(
                    f"Recurrence {field} must be between 1 and {MAX_OCCURRENCES}."
                )
            rule += f";{field.upper()}={number}"
    if value.get("until"):
        rule += ";UNTIL=" + iso_time(value["until"], "until").strftime("%Y%m%dT%H%M%SZ")
    return [rule]


def _dates(line, start):
    prefix, values = line.split(":", 1)
    parameters = dict(p.split("=", 1) for p in prefix.split(";")[1:])
    zone = ZoneInfo(parameters["TZID"]) if "TZID" in parameters else start.tzinfo
    dates = []
    for value in values.split(","):
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if len(value) == 8:
            parsed = parsed.replace(
                hour=start.hour, minute=start.minute, second=start.second
            )
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=zone)
        dates.append((value, parsed))
    return prefix, dates


def _rrule(line, start):
    parts = line.split(":", 1)[1].upper().split(";")
    for index, part in enumerate(parts):
        if part in {"FREQ=SECONDLY", "FREQ=MINUTELY", "FREQ=HOURLY"}:
            raise ValueError("Recurrence frequency must be daily or less frequent.")
        if part.startswith("UNTIL=") and len(part[6:]) == 8:
            end = datetime.strptime(part[6:], "%Y%m%d").replace(
                tzinfo=start.tzinfo
            ) + timedelta(days=1, seconds=-1)
            parts[index] = "UNTIL=" + end.astimezone(UTC).strftime("%Y%m%dT%H%M%SZ")
    count = next((int(p[6:]) for p in parts if p.startswith("COUNT=")), None)
    rule = rrulestr(
        "RRULE:" + ";".join(p for p in parts if not p.startswith("COUNT=")),
        dtstart=start,
    )
    return _CivilOccurrences(rule, start.tzinfo, count)


def rule_set(event):
    rules = recurrence_rules(event.get("recurrence"))
    if not rules:
        return None
    start = iso_time(event["startTime"], "startTime").astimezone(
        ZoneInfo(event.get("timezone") or "UTC")
    )
    result = rruleset()
    try:
        for line in rules:
            kind = line.split(":", 1)[0].split(";", 1)[0].upper()
            if kind in {"RRULE", "EXRULE"}:
                (result.rrule if kind == "RRULE" else result.exrule)(
                    _rrule(line, start)
                )
            elif kind in {"RDATE", "EXDATE"}:
                for _, date in _dates(line, start)[1]:
                    (result.rdate if kind == "RDATE" else result.exdate)(date)
            else:
                raise ValueError(
                    "Recurrence supports RRULE, EXRULE, RDATE and EXDATE; omit DTSTART/DTEND."
                )
    except (ValueError, TypeError, OverflowError) as error:
        raise ValueError(f"Invalid recurrence: {error}") from error
    return result


def split_rules(event, original):
    """Partition date lists and count each rule before applying exclusions."""
    cut = iso_time(original, "original_start_time")
    start = iso_time(event["startTime"], "startTime").astimezone(
        ZoneInfo(event.get("timezone") or "UTC")
    )
    old, future = [], []
    for line in recurrence_rules(event.get("recurrence")):
        kind = line.split(":", 1)[0].split(";", 1)[0].upper()
        if kind in {"RDATE", "EXDATE"}:
            prefix, dates = _dates(line, start)
            for destination, keep in (
                (old, lambda d: d < cut),
                (future, lambda d: d >= cut),
            ):
                values = [raw for raw, date in dates if keep(date)]
                if values:
                    destination.append(prefix + ":" + ",".join(values))
            continue
        parts = line.split(":", 1)[1].upper().split(";")
        count = next((int(p[6:]) for p in parts if p.startswith("COUNT=")), None)
        previous_count = 0
        for occurrence in _rrule(line, start):
            if occurrence >= cut:
                break
            previous_count += 1
            if previous_count > MAX_OCCURRENCES:
                raise ValueError("Series split exceeds occurrence limit.")
        if previous_count:
            # COUNT preserves earlier occurrences even when EXDATE suppresses some.
            old.append(
                kind
                + ":"
                + ";".join(p for p in parts if not p.startswith(("COUNT=", "UNTIL=")))
                + f";COUNT={previous_count}"
            )
        if count is None or count > previous_count:
            future.append(
                kind
                + ":"
                + ";".join(p for p in parts if not p.startswith("COUNT="))
                + (f";COUNT={count - previous_count}" if count else "")
            )
    return old, future


class _CivilOccurrences:
    """Invalid DST wall times do not consume an RRULE COUNT (RFC 5545)."""

    def __init__(self, rule, zone, count):
        self.rule, self.zone, self.count = rule, zone, count

    def __iter__(self):
        accepted = 0
        for value in self.rule:
            if value.astimezone(UTC).astimezone(self.zone).replace(
                tzinfo=None
            ) != value.replace(tzinfo=None):
                continue
            yield value
            accepted += 1
            if self.count is not None and accepted >= self.count:
                break
