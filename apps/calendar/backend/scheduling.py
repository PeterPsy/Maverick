"""Work windows and buffers shared by free-time search and first-free moves."""

from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo
from scalars import optional_int
from time_values import event_timezone


def scheduling_options(body):
    zone = ZoneInfo(event_timezone(body.get("timezone") or "UTC"))
    start = body.get("work_start")
    end = body.get("work_end")
    if bool(start) != bool(end):
        raise ValueError("work_start and work_end must be supplied together.")
    if start:
        try:
            start, end = time.fromisoformat(start), time.fromisoformat(end)
        except (ValueError, TypeError) as error:
            raise ValueError("Work hours must use HH:MM.") from error
        if start >= end:
            raise ValueError("work_end must be after work_start.")
    days = body.get("work_days", [1, 2, 3, 4, 5])
    if not isinstance(days, list) or not all(
        isinstance(d, int) and not isinstance(d, bool) and 0 <= d <= 6 for d in days
    ):
        raise ValueError("work_days must contain weekdays 0 (Sunday) to 6 (Saturday).")
    buffer = (
        optional_int(
            body.get("buffer_minutes"), field="buffer_minutes", minimum=0, maximum=1440
        )
        or 0
    )
    return {
        "zone": zone,
        "work_start": start,
        "work_end": end,
        "work_days": days,
        "buffer": timedelta(minutes=buffer),
    }


def free_slots(busy, start, end, duration, limit, options):
    """Intersect free gaps with civil working hours; merge overlapping busy intervals."""
    merged = []
    for left, right in sorted(
        (a - options["buffer"], b + options["buffer"]) for a, b in busy
    ):
        if merged and left <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(right, merged[-1][1]))
        else:
            merged.append((left, right))
    windows = [(start, end)]
    if options["work_start"]:
        windows = []
        day = start.astimezone(options["zone"]).date()
        last = end.astimezone(options["zone"]).date()
        if (last - day).days > 3660:
            raise ValueError("Working-hour searches are limited to ten years.")
        while day <= last:
            if (day.weekday() + 1) % 7 in options["work_days"]:
                left = max(
                    start, datetime.combine(day, options["work_start"], options["zone"])
                )
                right = min(
                    end, datetime.combine(day, options["work_end"], options["zone"])
                )
                if left < right:
                    windows.append((left, right))
            day += timedelta(days=1)
    result = []
    for left, right in windows:
        cursor = left
        gaps = []
        for busy_start, busy_end in merged:
            if busy_end <= cursor or busy_start >= right:
                continue
            if cursor < busy_start:
                gaps.append((cursor, min(busy_start, right)))
            cursor = max(cursor, busy_end)
        if cursor < right:
            gaps.append((cursor, right))
        for gap_start, gap_end in gaps:
            while gap_start + duration <= gap_end and len(result) < limit:
                result.append((gap_start, gap_start + duration))
                gap_start += duration
            if len(result) >= limit:
                return result
    return result
