"""CSV export with formula-injection protection.

Spreadsheet apps execute cells starting with = + - @ (and tab / carriage
return). Text cells that start with those characters are prefixed with a single
quote. Numbers are written as numbers, so negative values stay numeric.
"""

from __future__ import annotations

import csv
import io
from collections.abc import Iterable, Iterator
from datetime import date, datetime
from typing import Any

_DANGEROUS = ("=", "+", "-", "@", "\t", "\r")


def sanitize_cell(value: Any) -> Any:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return value
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    s = str(value)
    return "'" + s if s.startswith(_DANGEROUS) else s


def csv_stream(header: list[str], rows: Iterable[Iterable[Any]]) -> Iterator[str]:
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(header)
    yield buf.getvalue()
    for row in rows:
        buf.seek(0)
        buf.truncate()
        w.writerow([sanitize_cell(v) for v in row])
        yield buf.getvalue()
