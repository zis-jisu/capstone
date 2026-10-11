"""Normalize deadlines against the source message, never the execution clock."""
import re
from datetime import datetime, timedelta, timezone
from decimal import Decimal

KST = timezone(timedelta(hours=9))


def message_time(value):
    if not value:
        raise ValueError("Source message timestamp is required.")
    value = str(value)
    if re.fullmatch(r"\d+(?:\.\d+)?", value):
        seconds = Decimal(value)
        return (datetime(1970, 1, 1, tzinfo=timezone.utc)
                + timedelta(microseconds=int(seconds * 1000000))).astimezone(KST)
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        raise ValueError("Source timestamp must include a timezone.")
    return dt.astimezone(KST)


def normalize_deadline(deadline, source_timestamp=None):
    """Return {text, at}; date-only values stay date-only, not invented midnight.

    Common relative dates and explicit clock times are computed deterministically.
    For complex dates the extractor may supply an unambiguous date, but an exact
    clock time still has to occur in the original deadline text.
    """
    deadline = deadline or {}
    text = deadline.get("text")
    candidate = deadline.get("at")
    if not text:
        return {"text": text, "at": None}
    if re.search(r"빠른 시일|조만간|나중에|언젠가|가능한 빨리", text):
        return {"text": text, "at": None}
    day = None
    relative = re.search(r"오늘|내일|모레", text)
    if relative:
        if not source_timestamp:
            return {"text": text, "at": None}
        day = message_time(source_timestamp).date() + timedelta(
            days={"오늘": 0, "내일": 1, "모레": 2}[relative.group()])
    else:
        full = re.search(r"(\d{4})[-./년]\s*(\d{1,2})[-./월]\s*(\d{1,2})일?", text)
        if full:
            try:
                day = datetime(*map(int, full.groups())).date()
            except ValueError:
                return {"text": text, "at": None}
        elif candidate:
            try:
                day = datetime.fromisoformat(candidate.replace("Z", "+00:00")).date()
            except (ValueError, TypeError):
                return {"text": text, "at": None}
    if day is None:
        return {"text": text, "at": None}
    clocks = list(re.finditer(r"(?:(오전|오후)\s*)?(\d{1,2})(?:시(?:\s*(\d{1,2})분|\s*(반))?|:(\d{2}))", text))
    if len(clocks) != 1:
        # Multiple clock times mean an ambiguous range; do not pick one.
        return {"text": text, "at": day.isoformat() if not clocks else None}
    clock = clocks[0]
    period, hour, minute, half, colon_minute = clock.groups()
    hour = int(hour)
    minute = 30 if half else int(minute or colon_minute or 0)
    if period:
        if not 1 <= hour <= 12:
            return {"text": text, "at": None}
        hour = hour % 12 + (12 if period == "오후" else 0)
    elif hour < 12:
        # Bare '10시' doesn't establish AM/PM. 00:xx and 24h colon notation do.
        if "시" in clock.group():
            return {"text": text, "at": day.isoformat()}
    try:
        at = datetime(day.year, day.month, day.day, hour, minute, tzinfo=KST)
    except ValueError:
        return {"text": text, "at": None}
    return {"text": text, "at": at.isoformat()}


def db_timestamp(at):
    """Supabase timestamptz can only represent a confirmed date AND time."""
    if not at or len(at) == 10:
        return None
    dt = datetime.fromisoformat(at.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        raise ValueError("Deadline timestamp must include a timezone.")
    return dt.astimezone(KST).isoformat()
