"""CSV streaming for reports, matching the pattern the orders/stock/products exports use."""
import csv
from typing import Iterator


class _Echo:
    """A file-like object whose `write` returns the line, so `csv.writer` can be used as a
    generator source without buffering the whole report in memory."""

    def write(self, value: str) -> str:
        return value


def stream_csv(rows: list[dict]) -> Iterator[str]:
    """Header derived from the first row's keys, so a report's columns are its query's
    columns and the two cannot drift."""
    writer = csv.writer(_Echo())
    if not rows:
        yield writer.writerow(["no rows"])
        return
    headers = list(rows[0].keys())
    yield writer.writerow(headers)
    for row in rows:
        yield writer.writerow([row.get(h, "") for h in headers])
