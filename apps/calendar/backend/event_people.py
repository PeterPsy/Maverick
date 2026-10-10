"""Structured invitee metadata alongside the participant index used for planning."""

from constants import MAX_LIST_ITEMS


def attendee_details(value, attendees):
    if value is None:
        return []
    if not isinstance(value, list) or len(value) > MAX_LIST_ITEMS:
        raise ValueError("attendee_details must be a list of at most 50 participants.")
    selected = {str(item).casefold() for item in attendees}
    result = []
    for item in value:
        if not isinstance(item, dict):
            raise ValueError("Each attendee detail must be an object.")
        email = str(item.get("email") or "").strip()[:120]
        if not email or email.casefold() not in selected:
            continue
        person = {"email": email}
        for key in ("displayName", "comment", "id"):
            if item.get(key):
                person[key] = str(item[key])[:240]
        if item.get("responseStatus") in {
            "accepted",
            "declined",
            "tentative",
            "needsAction",
        }:
            person["responseStatus"] = item["responseStatus"]
        for key in ("optional", "organizer", "self", "resource"):
            if isinstance(item.get(key), bool):
                person[key] = item[key]
        guests = item.get("additionalGuests")
        if (
            isinstance(guests, int)
            and not isinstance(guests, bool)
            and 0 <= guests <= 1000
        ):
            person["additionalGuests"] = guests
        result.append(person)
    return result
