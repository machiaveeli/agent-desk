from pathlib import Path

import pytest

from agent_desk.providers.jsonl import read_json_lines


@pytest.fixture
def jsonl_path(tmp_path: Path) -> Path:
    return tmp_path / "session.jsonl"


@pytest.mark.parametrize(
    ("content", "expected"),
    [
        (b'{"type": "user"}\n', [{"type": "user"}]),
        (b'{"type": "user"}', [{"type": "user"}]),
        (b'{"type": "user"}\r\n', [{"type": "user"}]),
        (b'{"type": "us\n', [None]),
        (b"[1, 2]\n", [None]),
        (b'"just text"\n', [None]),
        (b"\xff\xfe\n", [None]),
        (b'{"a": 1}\n\n{"b": 2}\n', [{"a": 1}, {"b": 2}]),
    ],
    ids=[
        "object",
        "no-trailing-newline",
        "crlf",
        "corrupted",
        "array-is-not-an-object",
        "string-is-not-an-object",
        "invalid-utf8",
        "blank-lines-are-skipped",
    ],
)
def test_reads_one_object_per_line_and_none_for_invalid_lines(
    jsonl_path: Path, content: bytes, expected: list[dict[str, object] | None]
) -> None:
    jsonl_path.write_bytes(content)

    assert list(read_json_lines(jsonl_path)) == expected
