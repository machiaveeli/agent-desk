"""The condensed transcript of one session, read in a background thread."""

from collections.abc import Iterator
from itertools import batched
from typing import ClassVar

from textual import work
from textual.app import ComposeResult
from textual.binding import Binding, BindingType
from textual.screen import Screen
from textual.widgets import Footer, Header, RichLog, Static
from textual.worker import get_current_worker

from agent_desk.display import format_title
from agent_desk.domain.models import SessionSummary, TranscriptEntry
from agent_desk.services.catalog import CatalogService

# Entries handed to the screen at once: few enough that the first ones show up quickly,
# many enough that a long transcript is not redrawn once per line.
BATCH_SIZE = 200
ROLE_LABELS = {"user": "You", "assistant": "Assistant"}
TOOL_INDENT = "  "


class TranscriptScreen(Screen[None]):
    BINDINGS: ClassVar[list[BindingType]] = [Binding("escape", "back", "Back")]

    def __init__(self, catalog: CatalogService, summary: SessionSummary) -> None:
        super().__init__()
        self.catalog = catalog
        self.summary = summary
        self.entry_count = 0

    def compose(self) -> ComposeResult:
        yield Header()
        # Starts at the top: a transcript is read from the beginning.
        yield RichLog(wrap=True, auto_scroll=False, id="transcript")
        yield Static("Loading…", id="note")
        yield Footer()

    def on_mount(self) -> None:
        self.sub_title = format_title(self.summary.title)
        self.query_one(RichLog).focus()
        self.load_transcript()

    @work(thread=True)
    def load_transcript(self) -> None:
        """Runs in a thread, so a large file never freezes the screen. Leaving the screen
        cancels the worker; it stops at the next batch."""
        worker = get_current_worker()
        try:
            for batch in batched(self.read_entries(), BATCH_SIZE):
                if worker.is_cancelled:
                    return
                self.app.call_from_thread(self.show_entries, batch)
        except OSError:
            note = f"Error: could not read {self.summary.session.path.name}."
        else:
            note = f"{self.entry_count} entries."
        if not worker.is_cancelled:
            self.app.call_from_thread(self.show_note, note)

    def read_entries(self) -> Iterator[TranscriptEntry]:
        return self.catalog.read_transcript(self.summary.session)

    def show_entries(self, entries: tuple[TranscriptEntry, ...]) -> None:
        # Escape may have closed the screen after the worker checked for cancellation.
        if not self.is_open():
            return
        log = self.query_one(RichLog)
        for entry in entries:
            log.write(format_entry(entry))
        self.entry_count += len(entries)

    def show_note(self, note: str) -> None:
        if self.is_open():
            self.query_one("#note", Static).update(note)

    def is_open(self) -> bool:
        return self in self.app.screen_stack

    def action_back(self) -> None:
        self.app.pop_screen()


def format_entry(entry: TranscriptEntry) -> str:
    """Tool calls are already collapsed to one line: the tool name and its main argument.
    The log shows it as plain text (no markup), so brackets in a message stay as typed."""
    if entry.role == "tool":
        return f"{TOOL_INDENT}[{entry.tool_name}] {entry.text}"
    return f"{ROLE_LABELS[entry.role]}: {entry.text}"
