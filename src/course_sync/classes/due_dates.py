from __future__ import annotations

from datetime import datetime


_DATE_FORMATS = (
    ("%d.%m.%Y %H:%M:%S", False),
    ("%d.%m.%Y %H:%M", False),
    ("%d.%m.%Y", True),
    ("%Y-%m-%dT%H:%M:%S", False),
    ("%Y-%m-%dT%H:%M", False),
    ("%Y-%m-%d %H:%M:%S", False),
    ("%Y-%m-%d %H:%M", False),
    ("%Y-%m-%d", True),
)


def normalize_h5p_due_date(value: str) -> str:
    """Return a JavaScript-parseable local datetime for H5P due date fields."""
    raw_value = str(value or "").strip()
    if not raw_value:
        return ""

    for date_format, is_date_only in _DATE_FORMATS:
        try:
            parsed = datetime.strptime(raw_value, date_format)
        except ValueError:
            continue
        if is_date_only:
            parsed = parsed.replace(hour=23, minute=59)
        return parsed.strftime("%Y-%m-%dT%H:%M:%S")

    return raw_value
