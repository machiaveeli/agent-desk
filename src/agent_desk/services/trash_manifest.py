"""Reads and writes `manifest.json`, the file that describes one trash entry.

The format is persisted on the user's disk, so it only changes with a new `version`."""

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import get_args

from agent_desk.domain.models import TrashEntry, TrashEntryState, TrashItem, TrashItemKind

MANIFEST_FILE_NAME = "manifest.json"
MANIFEST_VERSION = 1
TIMESTAMP_FORMAT = "%Y-%m-%dT%H:%M:%SZ"
TEMPORARY_SUFFIX = ".tmp"


@dataclass(frozen=True)
class ManifestError:
    """The manifest cannot be trusted: unreadable, not JSON, or not in the expected shape."""

    detail: str


def write_manifest(entry_dir: Path, entry: TrashEntry) -> None:
    """Writes to a temporary file first and then replaces, so a crash never leaves half a
    manifest behind: the old one or the new one is on disk, never a mix."""
    content = json.dumps(encode_entry(entry), indent=2, ensure_ascii=False) + "\n"
    target = entry_dir / MANIFEST_FILE_NAME
    temporary = target.with_name(target.name + TEMPORARY_SUFFIX)
    temporary.write_bytes(content.encode("utf-8"))
    temporary.replace(target)


def read_manifest(entry_dir: Path) -> TrashEntry | ManifestError:
    try:
        content = (entry_dir / MANIFEST_FILE_NAME).read_bytes()
    except OSError as error:
        return ManifestError(f"cannot read the manifest: {error.strerror}")
    try:
        raw = json.loads(content)
    except (UnicodeDecodeError, json.JSONDecodeError):
        return ManifestError("the manifest is not valid JSON")
    try:
        return decode_entry(raw)
    except (KeyError, TypeError, ValueError) as error:
        return ManifestError(f"the manifest has an unexpected shape ({error})")


def encode_entry(entry: TrashEntry) -> dict[str, object]:
    return {
        "version": MANIFEST_VERSION,
        "entry_id": entry.entry_id,
        "state": entry.state,
        "provider_id": entry.provider_id,
        "session_id": entry.session_id,
        "cwd": None if entry.cwd is None else str(entry.cwd),
        "title": entry.title,
        "trashed_at": entry.trashed_at.astimezone(UTC).strftime(TIMESTAMP_FORMAT),
        "items": [encode_item(item) for item in entry.items],
    }


def encode_item(item: TrashItem) -> dict[str, object]:
    return {
        "original_path": str(item.original_path),
        "stored_name": item.stored_name,
        "kind": item.kind,
        "size_bytes": item.size_bytes,
    }


def decode_entry(raw: object) -> TrashEntry:
    """Raises KeyError, TypeError or ValueError on anything off; read_manifest turns them into
    a ManifestError."""
    fields = require(raw, dict)
    version = require(fields["version"], int)
    if version != MANIFEST_VERSION:
        raise ValueError(f"unsupported version {version}")
    cwd = fields["cwd"]
    return TrashEntry(
        entry_id=require(fields["entry_id"], str),
        state=require_choice(fields["state"], get_args(TrashEntryState.__value__)),
        provider_id=require(fields["provider_id"], str),
        session_id=require(fields["session_id"], str),
        cwd=None if cwd is None else Path(require(cwd, str)),
        title=require(fields["title"], str),
        trashed_at=datetime.strptime(require(fields["trashed_at"], str), TIMESTAMP_FORMAT).replace(
            tzinfo=UTC
        ),
        items=tuple(decode_item(item) for item in require(fields["items"], list)),
    )


def decode_item(raw: object) -> TrashItem:
    fields = require(raw, dict)
    stored_name = require(fields["stored_name"], str)
    # The stored name becomes a path inside the entry; anything else could point outside it.
    if Path(stored_name).name != stored_name or stored_name in {"", ".", ".."}:
        raise ValueError(f"invalid stored name {stored_name!r}")
    size_bytes = require(fields["size_bytes"], int)
    if size_bytes < 0:
        raise ValueError("negative size")
    original_path = Path(require(fields["original_path"], str))
    # Restore writes here, so a relative path would land wherever agent-desk happens to run.
    if not original_path.is_absolute():
        raise ValueError(f"original path {original_path} is not absolute")
    return TrashItem(
        original_path=original_path,
        stored_name=stored_name,
        kind=require_choice(fields["kind"], get_args(TrashItemKind.__value__)),
        size_bytes=size_bytes,
    )


def require[T](value: object, expected: type[T]) -> T:
    # bool is a subclass of int in Python, so `true` would otherwise pass as 1.
    if not isinstance(value, expected) or (expected is int and isinstance(value, bool)):
        raise TypeError(f"expected {expected.__name__}, got {type(value).__name__}")
    return value


def require_choice[T: str](value: object, choices: tuple[T, ...]) -> T:
    for choice in choices:
        if value == choice:
            return choice
    raise ValueError(f"{value!r} is not one of {', '.join(choices)}")
