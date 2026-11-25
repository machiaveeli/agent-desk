"""The app's own trash: sessions move here whole and can move back, byte for byte.

Each entry is a folder `<root>/<entry-id>/` with `manifest.json` and the moved files under
`files/`. Only `trash empty` deletes anything for good."""

from collections.abc import Callable, Iterator
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path

from agent_desk.domain.errors import TrashError
from agent_desk.domain.models import Session, SessionSummary, TrashEntry, TrashItem
from agent_desk.services.trash_manifest import (
    MANIFEST_FILE_NAME,
    ManifestError,
    read_manifest,
    write_manifest,
)

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
        refusal = self.find_trash_refusal(session)
        if refusal is not None:
            return refusal
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

    def restore(self, entry_id: str) -> TrashEntry | TrashError:
        """Moves every item back to its original path, then removes the entry. Checks every
        item first, so a refusal leaves both the trash and the provider folders untouched."""
        entry_dir = self.find_entry_dir(entry_id)
        if entry_dir is None:
            return TrashError("entry_not_found", f"no trash entry with id {entry_id!r}.")
        entry = read_manifest(entry_dir)
        if isinstance(entry, ManifestError):
            return TrashError("corrupted_manifest", f"{entry_id}: {entry.detail}.")
        if entry.entry_id != entry_dir.name:
            return TrashError(
                "corrupted_manifest", f"{entry_id}: the manifest names another entry."
            )
        files_dir = entry_dir / FILES_DIR_NAME
        to_move = find_items_to_move_back(entry, files_dir)
        if isinstance(to_move, TrashError):
            return to_move
        for item in to_move:
            item.original_path.parent.mkdir(parents=True, exist_ok=True)
            self.move(files_dir / item.stored_name, item.original_path)
        remove_empty_entry(entry_dir)
        return entry

    def find_trash_refusal(self, session: Session) -> TrashError | None:
        missing = next((path for path in session.files() if not path.exists()), None)
        if missing is not None:
            return TrashError("not_found", f"{missing.name} no longer exists.")
        if self.is_active(session):
            return TrashError(
                "session_active",
                "the session is still open; close it before moving it to the trash.",
            )
        if self.find_entry(session) is not None:
            return TrashError(
                "already_trashed", "this session already has a trash entry; restore it first."
            )
        return None

    def find_entry_dir(self, entry_id: str) -> Path | None:
        # The id comes from the user, so it must name a folder directly inside the trash.
        if Path(entry_id).name != entry_id or entry_id in {"", ".", ".."}:
            return None
        entry_dir = self.root / entry_id
        return entry_dir if entry_dir.is_dir() else None

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


def find_items_to_move_back(entry: TrashEntry, files_dir: Path) -> list[TrashItem] | TrashError:
    """The items whose stored copy is in the trash. A pending entry may have items that never
    left their original path; those stay where they are."""
    to_move: list[TrashItem] = []
    for item in entry.items:
        is_stored = (files_dir / item.stored_name).exists()
        is_at_origin = item.original_path.exists()
        if is_stored and is_at_origin:
            return TrashError(
                "conflict", f"{item.original_path} exists again; move it away and try again."
            )
        if not is_stored and not is_at_origin:
            return TrashError(
                "missing_files", f"{item.stored_name} is missing from the trash entry."
            )
        if is_stored:
            to_move.append(item)
    return to_move


def remove_empty_entry(entry_dir: Path) -> None:
    """rmdir, not rmtree: anything still inside means something went wrong, so it fails loudly
    instead of deleting it."""
    files_dir = entry_dir / FILES_DIR_NAME
    if files_dir.exists():
        files_dir.rmdir()
    (entry_dir / MANIFEST_FILE_NAME).unlink()
    entry_dir.rmdir()
