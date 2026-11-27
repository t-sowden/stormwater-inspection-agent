"""Read clock times and site-local datetimes as people (and Excel) write them. Plain Python.

Saving a CSV in Excel rewrites "07:00" as "7:00" and "2026-11-09 09:00" as "11/9/2026 9:00".
Both forms mean the same thing, so every module parses these fields here, never with string compares.
"""
import re
from datetime import datetime

CLOCK_RE = re.compile(r"^\d{1,2}:\d{2}(:\d{2})?(\s?[AP]M)?$", re.I)
CLOCK_FORMATS = ["%H:%M", "%H:%M:%S", "%I:%M %p", "%I:%M:%S %p", "%I:%M%p", "%I:%M:%S%p"]
US_DATETIME_FORMATS = ["%m/%d/%Y %H:%M", "%m/%d/%Y %H:%M:%S", "%m/%d/%Y %I:%M %p", "%m/%d/%Y %I:%M:%S %p",
                       "%m/%d/%Y"]


def _clean(text):
    return " ".join(str(text if text is not None else "").split())


def _prefix(where):
    return f"{where}: " if where else ""


def parse_clock(text, where=None):
    """'7:00', '07:00', '07:00:00', '7:00 AM' -> datetime.time. `where` names the field in errors."""
    value = _clean(text).upper()
    if CLOCK_RE.match(value):
        for fmt in CLOCK_FORMATS:
            try:
                return datetime.strptime(value, fmt).time()
            except ValueError:
                pass
    raise ValueError(f"{_prefix(where)}unreadable time '{text}'. Use H:MM or HH:MM, 24-hour "
                     "(e.g. 7:00 or 17:00), or h:MM AM/PM.")


def parse_local_datetime(text, where=None):
    """Site-local date and time -> naive datetime.

    Accepts YYYY-MM-DD HH:MM (or with seconds), M/D/YYYY H:MM, M/D/YYYY h:MM AM/PM, and M/D/YYYY
    (midnight). `where` names the file/row/field in errors.
    """
    value = _clean(text)
    if value:
        try:
            return datetime.fromisoformat(value).replace(tzinfo=None)
        except ValueError:
            pass
        for fmt in US_DATETIME_FORMATS:
            try:
                return datetime.strptime(value.upper(), fmt)
            except ValueError:
                pass
    raise ValueError(f"{_prefix(where)}unreadable time '{text}'. Use YYYY-MM-DD HH:MM (e.g. 2026-11-09 09:00) "
                     "or M/D/YYYY H:MM (e.g. 11/9/2026 9:00).")


def clock_text(value):
    """time -> 'HH:MM' (how the app writes clock times)."""
    return value.strftime("%H:%M")


def datetime_text(value):
    """datetime -> 'YYYY-MM-DD HH:MM' (how the app writes site-local times)."""
    return value.strftime("%Y-%m-%d %H:%M")
