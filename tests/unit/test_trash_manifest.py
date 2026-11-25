import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from agent_desk.domain.models import TrashEntry, TrashItem
from agent_desk.services.trash_manifest import ManifestError, read_manifest, write_manifest

ORIGINAL = Path("/work/claude/projects/-work-app/3f2a9c1e.jsonl").absolute()
ENTRY = TrashEntry(
    entry_id="20261123T140512Z-3f2a9c1e",
    state="complete",
    provider_id="claude-code",
    session_id="3f2a9c1e",
    cwd=Path("/work/app"),
    title="Corrigir o login ✓",
    trashed_at=datetime(2026, 11, 23, 14, 5, 12, tzinfo=UTC),
    items=(TrashItem(ORIGINAL, "3f2a9c1e.jsonl", "file", 120),),
)
VALID_ITEM: dict[str, object] = {
    "original_path": str(ORIGINAL),
    "stored_name": "3f2a9c1e.jsonl",
    "kind": "file",
    "size_bytes": 120,
}
VALID: dict[str, object] = {
    "version": 1,
    "entry_id": "20261123T140512Z-3f2a9c1e",
    "state": "complete",
    "provider_id": "claude-code",
    "session_id": "3f2a9c1e",
    "cwd": None,
    "title": "t",
    "trashed_at": "2026-11-23T14:05:12Z",
    "items": [VALID_ITEM],
}


def write_raw(entry_dir: Path, content: bytes) -> None:
    entry_dir.mkdir(exist_ok=True)
    (entry_dir / "manifest.json").write_bytes(content)


def with_item(**changes: object) -> dict[str, object]:
    return {**VALID, "items": [{**VALID_ITEM, **changes}]}


def test_an_entry_written_and_read_back_is_the_same_entry(tmp_path: Path) -> None:
    write_manifest(tmp_path, ENTRY)

    assert read_manifest(tmp_path) == ENTRY


def test_rewriting_the_manifest_leaves_no_temporary_file(tmp_path: Path) -> None:
    write_manifest(tmp_path, ENTRY)
    write_manifest(tmp_path, ENTRY)

    assert sorted(path.name for path in tmp_path.iterdir()) == ["manifest.json"]


def test_a_valid_manifest_without_cwd_reads_as_none(tmp_path: Path) -> None:
    write_raw(tmp_path, json.dumps(VALID).encode())

    entry = read_manifest(tmp_path)

    assert isinstance(entry, TrashEntry)
    assert entry.cwd is None


def test_a_missing_manifest_is_reported(tmp_path: Path) -> None:
    assert isinstance(read_manifest(tmp_path), ManifestError)


@pytest.mark.parametrize(
    "content",
    [
        b'{"version": 1, "entry_',
        b'{"title": "\xff"}',
        b"[]",
        json.dumps({**VALID, "version": 2}).encode(),
        json.dumps({**VALID, "version": True}).encode(),
        json.dumps({key: value for key, value in VALID.items() if key != "title"}).encode(),
        json.dumps({**VALID, "state": "deleted"}).encode(),
        json.dumps({**VALID, "trashed_at": "yesterday"}).encode(),
        json.dumps({**VALID, "cwd": 3}).encode(),
        json.dumps({**VALID, "items": {}}).encode(),
        json.dumps(with_item(kind="link")).encode(),
        json.dumps(with_item(size_bytes=-1)).encode(),
        json.dumps(with_item(size_bytes="120")).encode(),
        json.dumps(with_item(stored_name="../escape")).encode(),
        json.dumps(with_item(stored_name="..")).encode(),
        json.dumps(with_item(stored_name="")).encode(),
        json.dumps(with_item(original_path="relative/file.jsonl")).encode(),
    ],
    ids=[
        "truncated",
        "not-utf8",
        "not-an-object",
        "unknown-version",
        "bool-version",
        "missing-field",
        "unknown-state",
        "bad-date",
        "cwd-not-string",
        "items-not-list",
        "unknown-kind",
        "negative-size",
        "size-not-int",
        "stored-name-escapes",
        "stored-name-parent",
        "stored-name-empty",
        "relative-original",
    ],
)
def test_a_manifest_that_cannot_be_trusted_is_reported(tmp_path: Path, content: bytes) -> None:
    write_raw(tmp_path, content)

    assert isinstance(read_manifest(tmp_path), ManifestError)
