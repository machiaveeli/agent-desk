import json
from collections.abc import Generator
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
