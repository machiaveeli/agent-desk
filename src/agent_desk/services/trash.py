"""The app's own trash: sessions move here whole and can move back, byte for byte.

Each entry is a folder `<root>/<entry-id>/` with `manifest.json` and the moved files under
`files/`. Only `trash empty` deletes anything for good."""

from collections.abc import Callable, Iterator
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path

from agent_desk.domain.errors import TrashError
from agent_desk.domain.models import Session, SessionSummary, TrashEntry, TrashItem
from agent_desk.services.trash_manifest import ManifestError, read_manifest, write_manifest

FILES_DIR_NAME = "files"
ENTRY_ID_TIME_FORMAT = "%Y%m%dT%H%M%SZ"
SHORT_SESSION_ID_LENGTH = 8
FIRST_DUPLICATE_SUFFIX = 2

type Clock = Callable[[], datetime]
type Mover = Callable[[Path, Path], None]
type ActivityCheck = Callable[[Session], bool]


def move_path(source: Path, target: Path) -> None:
    source.rename(target)


@dataclass(frozen=True)
class TrashService:
    root: Path
    is_active: ActivityCheck
    # Injected so tests control the time stamped on entries and can make a move fail.
    now: Clock
    move: Mover = move_path

    def trash(self, summary: SessionSummary) -> TrashEntry | TrashError:
        session = summary.session
        if self.find_entry(session) is not None:
            return TrashError(
                "already_trashed", "this session already has a trash entry; restore it first."
            )
        trashed_at = self.now().astimezone(UTC).replace(microsecond=0)
        entry_dir = self.create_entry_dir(session, trashed_at)
        entry = TrashEntry(
            entry_id=entry_dir.name,
            state="pending",
            provider_id=session.provider_id,
            session_id=session.session_id,
            cwd=session.cwd,
            title=summary.title,
            trashed_at=trashed_at,
            items=tuple(describe_item(path) for path in session.files()),
        )
        # Written before anything moves: if the process dies halfway, the pending manifest
        # still says where every item came from.
        write_manifest(entry_dir, entry)
        files_dir = entry_dir / FILES_DIR_NAME
        files_dir.mkdir()
        for item in entry.items:
            self.move(item.original_path, files_dir / item.stored_name)
        complete = replace(entry, state="complete")
        write_manifest(entry_dir, complete)
        return complete

    def find_entry(self, session: Session) -> TrashEntry | None:
        for entry in self.read_entries():
            if isinstance(entry, TrashEntry) and (entry.provider_id, entry.session_id) == (
                session.provider_id,
                session.session_id,
            ):
                return entry
        return None

    def read_entries(self) -> Iterator[TrashEntry | ManifestError]:
        if not self.root.is_dir():
            return
        for entry_dir in sorted(self.root.iterdir()):
            if entry_dir.is_dir():
                yield read_manifest(entry_dir)

    def create_entry_dir(self, session: Session, trashed_at: datetime) -> Path:
        """`<time>-<short session id>`, so a plain listing sorts by date. Two sessions can share
        the short id in the same second; the second one gets a `-2` suffix, and so on."""
        self.root.mkdir(parents=True, exist_ok=True)
        short_id = session.session_id[:SHORT_SESSION_ID_LENGTH]
        base_id = f"{trashed_at.strftime(ENTRY_ID_TIME_FORMAT)}-{short_id}"
        candidate = self.root / base_id
        suffix = FIRST_DUPLICATE_SUFFIX
        while True:
            try:
                candidate.mkdir()
                return candidate
            except FileExistsError:
                candidate = self.root / f"{base_id}-{suffix}"
                suffix += 1


def describe_item(path: Path) -> TrashItem:
    if path.is_dir():
        size = sum(child.lstat().st_size for child in path.rglob("*") if child.is_file())
        return TrashItem(path, path.name, "dir", size)
    return TrashItem(path, path.name, "file", path.lstat().st_size)
