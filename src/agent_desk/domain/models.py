from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Literal


@dataclass(frozen=True)
class Project:
    """A working directory whose sessions one provider keeps in `storage_dir`.

    `cwd` comes from inside the session files, never from the folder name. Two projects can
    share a `storage_dir` when the provider encodes their cwds to the same folder name. `cwd` is
    None when no session reveals it, for example a folder that only holds memory.
    """

    provider_id: str
    storage_dir: Path
    cwd: Path | None


@dataclass(frozen=True)
class Session:
    provider_id: str
    session_id: str
    path: Path
    sibling_dir: Path | None
    cwd: Path | None

    def files(self) -> tuple[Path, ...]:
        """Everything on disk that belongs to the session, so it can move as one unit."""
        if self.sibling_dir is None:
            return (self.path,)
        return (self.path, self.sibling_dir)


@dataclass(frozen=True)
class SessionSummary:
    """Metadata shown in the session list. Timestamps are both set or both None."""

    session: Session
    title: str
    started_at: datetime | None
    ended_at: datetime | None
    first_prompt: str | None
    size_bytes: int
    invalid_line_count: int

    def __post_init__(self) -> None:
        # A violation here is a bug in the provider, not an expected failure, so it raises.
        validate_time_range(self.started_at, self.ended_at)
        if self.size_bytes < 0 or self.invalid_line_count < 0:
            raise ValueError(
                f"size ({self.size_bytes}) and invalid lines ({self.invalid_line_count}) "
                "cannot be negative"
            )


@dataclass(frozen=True)
class MemoryFile:
    provider_id: str
    path: Path


type TranscriptRole = Literal["user", "assistant", "tool"]


@dataclass(frozen=True)
class TranscriptEntry:
    """One line of the condensed transcript. `tool_name` is set only for collapsed tool calls."""

    role: TranscriptRole
    text: str
    tool_name: str | None = None


type TrashItemKind = Literal["file", "dir"]
# "pending" from the moment the manifest is written until every item has moved.
type TrashEntryState = Literal["pending", "complete"]


@dataclass(frozen=True)
class TrashItem:
    """One file or folder of a trashed session, kept as `files/<stored_name>` in its entry."""

    original_path: Path
    stored_name: str
    kind: TrashItemKind
    size_bytes: int


@dataclass(frozen=True)
class TrashEntry:
    """A session in the trash. `cwd` and `title` are saved when it is trashed, so the trash can
    be listed without reading the stored files."""

    entry_id: str
    state: TrashEntryState
    provider_id: str
    session_id: str
    cwd: Path | None
    title: str
    trashed_at: datetime
    items: tuple[TrashItem, ...]

    @property
    def size_bytes(self) -> int:
        return sum(item.size_bytes for item in self.items)


def validate_time_range(started_at: datetime | None, ended_at: datetime | None) -> None:
    if started_at is None and ended_at is None:
        return
    if started_at is None or ended_at is None:
        raise ValueError("started_at and ended_at must be both set or both None")
    # Naive datetimes cannot be compared with aware ones, so they are refused up front.
    if started_at.tzinfo is None or ended_at.tzinfo is None:
        raise ValueError("session timestamps must be timezone-aware")
    if ended_at < started_at:
        raise ValueError(f"session ends ({ended_at}) before it starts ({started_at})")
