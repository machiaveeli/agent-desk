import json
from collections.abc import Generator
from datetime import datetime
from pathlib import Path

type JsonObject = dict[str, object]


def read_json_lines(path: Path) -> Generator[JsonObject | None, None, None]:
    """Streams a JSONL file one line at a time, so large sessions are never loaded whole.

    Yields None for a line that is not a JSON object, letting callers count it instead of
    failing. Blank lines are skipped.
    """
    with path.open("rb") as file:
        for raw_line in file:
            if raw_line.strip():
                yield parse_json_object(raw_line)


def parse_json_object(raw_line: bytes) -> JsonObject | None:
    try:
        value = json.loads(raw_line.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def read_text(value: object) -> str | None:
    return (value.strip() or None) if isinstance(value, str) else None


def parse_timestamp(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        moment = datetime.fromisoformat(value)
    except ValueError:
        return None
    # A timestamp without a timezone cannot be placed in time reliably, so it is ignored.
    return moment if moment.tzinfo is not None else None
