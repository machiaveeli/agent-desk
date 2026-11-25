"""The app trash: what is in it, newest first, and `u` to restore the selected entry."""

from collections.abc import Iterable, Sequence
from typing import ClassVar

from textual.binding import Binding, BindingType
from textual.coordinate import Coordinate
from textual.widgets import DataTable

from agent_desk.display import (
    format_cwd,
    format_moment,
    format_size,
    format_title,
    format_trash_status,
)
from agent_desk.domain.errors import TrashError
from agent_desk.services.trash import ListedEntry, TrashService, UnreadableEntry
from agent_desk.tui.table_screen import TableRow, TableScreen


class TrashScreen(TableScreen):
    BINDINGS: ClassVar[list[BindingType]] = [Binding("u", "restore", "Restore")]
    COLUMNS = ("Status", "Trashed", "Size", "Provider", "Project", "Title")
    FILTER_PLACEHOLDER = "Filter by title, project or provider (press /)"

    def __init__(self, trash: TrashService) -> None:
        super().__init__()
        self.trash = trash
        self.entries: list[ListedEntry] = []

    def load(self) -> None:
        listing = self.trash.list_entries()
        self.entries = listing.entries
        self.show_note(describe_notes(listing.entries, listing.unreadable))
        self.sub_title = "trash"

    def rows(self, filter_text: str) -> Iterable[TableRow]:
        for index, listed in enumerate(self.entries):
            if matches_filter(listed, filter_text):
                yield str(index), format_trash_row(listed)

    def leave(self) -> None:
        # dismiss, not pop_screen: the projects screen reloads in its callback.
        self.dismiss()

    def action_restore(self) -> None:
        table = self.query_one(DataTable)
        if table.row_count == 0:
            return
        row_key = table.coordinate_to_cell_key(Coordinate(table.cursor_row, 0)).row_key
        entry = self.entries[int(str(row_key.value))].entry
        result = self.trash.restore(entry.entry_id)
        if isinstance(result, TrashError):
            self.notify(f"Cannot restore: {result.detail}", severity="error", markup=False)
            return
        self.notify(f"Restored '{format_title(result.title)}'.", markup=False)
        self.load()
        self.show_rows()


def matches_filter(listed: ListedEntry, filter_text: str) -> bool:
    needle = filter_text.strip().casefold()
    entry = listed.entry
    haystack = f"{format_title(entry.title)} {format_cwd(entry.cwd)} {entry.provider_id}"
    return needle in haystack.casefold()


def format_trash_row(listed: ListedEntry) -> tuple[str, ...]:
    entry = listed.entry
    return (
        format_trash_status(listed),
        format_moment(entry.trashed_at, None),
        format_size(entry.size_bytes),
        entry.provider_id,
        format_cwd(entry.cwd),
        format_title(entry.title),
    )


def describe_notes(entries: Sequence[ListedEntry], unreadable: Sequence[UnreadableEntry]) -> str:
    notes = [f"Note: entry {item.entry_id} cannot be read: {item.detail}." for item in unreadable]
    if not entries:
        notes.append("The trash is empty.")
    return "\n".join(notes)
