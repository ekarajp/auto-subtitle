from __future__ import annotations

import re


TIMECODE_RE = re.compile(
    r"^\s*(?:(?P<hours>\d{1,2}):)?(?P<minutes>\d{1,2}):(?P<seconds>\d{1,2})(?P<fraction>[,.]\d{1,3})?\s*$"
)


class TimecodeError(ValueError):
    """Raised when a subtitle timecode cannot be parsed."""


def parse_timecode(value: str | int | float) -> float:
    if isinstance(value, (int, float)):
        seconds = float(value)
        if seconds < 0:
            raise TimecodeError("Timecode cannot be negative.")
        return seconds

    text = str(value).strip()
    if not text:
        raise TimecodeError("Empty timecode.")

    try:
        seconds = float(text)
    except ValueError:
        seconds = None
    if seconds is not None:
        if seconds < 0:
            raise TimecodeError("Timecode cannot be negative.")
        return seconds

    match = TIMECODE_RE.match(text)
    if not match:
        raise TimecodeError(f"Invalid timecode: {value!r}")

    hours = int(match.group("hours") or 0)
    minutes = int(match.group("minutes"))
    secs = int(match.group("seconds"))
    fraction = match.group("fraction") or ""

    if minutes > 59 or secs > 59:
        raise TimecodeError(f"Invalid timecode range: {value!r}")

    millis = int(fraction[1:].ljust(3, "0")[:3]) if fraction else 0
    return (hours * 3600) + (minutes * 60) + secs + (millis / 1000.0)


def format_timecode(seconds: float, separator: str = ".") -> str:
    if seconds < 0:
        seconds = 0
    millis_total = int(round(seconds * 1000))
    hours, rem = divmod(millis_total, 3_600_000)
    minutes, rem = divmod(rem, 60_000)
    secs, millis = divmod(rem, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}{separator}{millis:03d}"


def format_ass_time(seconds: float) -> str:
    if seconds < 0:
        seconds = 0
    centis_total = int(round(seconds * 100))
    hours, rem = divmod(centis_total, 360_000)
    minutes, rem = divmod(rem, 6_000)
    secs, centis = divmod(rem, 100)
    return f"{hours}:{minutes:02d}:{secs:02d}.{centis:02d}"


def pretty_duration(seconds: float) -> str:
    return format_timecode(seconds, ".")
