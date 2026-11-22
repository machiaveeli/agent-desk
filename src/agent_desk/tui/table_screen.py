"""A screen with a text filter over a table, a note line and the key footer."""

from collections.abc import Iterable
from typing import ClassVar

from textual.app import ComposeResult
from textual.binding import Binding, BindingType
from textual.screen import Screen
from textual.widgets import DataTable, Footer, Header, Input, Static

type TableRow = tuple[str, tuple[str, ...]]
"""A row key and its cells."""


class TableScreen(Screen[None]):
    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("slash", "focus_filter", "Filter"),
        Binding("escape", "back", "Back"),
    ]
    COLUMNS: ClassVar[tuple[str, ...]]
    FILTER_PLACEHOLDER: ClassVar[str]

    def compose(self) -> ComposeResult:
        yield Header()
        yield Input(placeholder=self.FILTER_PLACEHOLDER, id="filter")
        yield DataTable(cursor_type="row", id="table")
        yield Static(id="note")
        yield Footer()

    def on_mount(self) -> None:
        self.query_one(DataTable).add_columns(*self.COLUMNS)
        self.load()
        self.show_rows()
        self.query_one(DataTable).focus()

    def load(self) -> None:
        """Reads the data from the services. Runs once, when the screen opens."""
        raise NotImplementedError

    def rows(self, filter_text: str) -> Iterable[TableRow]:
        raise NotImplementedError

    def leave(self) -> None:
        """What Escape does once the filter no longer has the focus."""
        raise NotImplementedError

    def show_note(self, text: str) -> None:
        self.query_one("#note", Static).update(text)

    def show_rows(self) -> None:
        table = self.query_one(DataTable)
        table.clear()
        for key, cells in self.rows(self.query_one(Input).value):
            table.add_row(*cells, key=key)

    def on_input_changed(self, event: Input.Changed) -> None:
        self.show_rows()

    def action_focus_filter(self) -> None:
        self.query_one(Input).focus()

    def action_back(self) -> None:
        if self.query_one(Input).has_focus:
            self.query_one(DataTable).focus()
            return
        self.leave()
