"""The sessions of one project, sortable by date or size, with a title and date filter."""

from collections.abc import Iterable
from typing import ClassVar, Literal

from textual.binding import Binding, BindingType
from textual.widgets import DataTable

from agent_desk.display import format_moment, format_project_label, format_size, format_title
from agent_desk.domain.models import Project, SessionSummary
from agent_desk.services.catalog import CatalogService, sort_most_recent_first
from agent_desk.tui.table_screen import TableRow, TableScreen
from agent_desk.tui.transcript_screen import TranscriptScreen

type SortOrder = Literal["date", "size"]

ACTIVE_LABEL = "active"


class SessionsScreen(TableScreen):
    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("s", "toggle_sort", "Sort by date/size"),
    ]
    COLUMNS = ("State", "Title", "Started", "Ended", "Size")
    FILTER_PLACEHOLDER = "Filter by title or date, e.g. 2026-01 (press /)"

    def __init__(self, catalog: CatalogService, project: Project) -> None:
        super().__init__()
        self.catalog = catalog
        self.project = project
        self.summaries: list[SessionSummary] = []
        self.active_ids: set[str] = set()
        self.session_order: SortOrder = "date"

    def load(self) -> None:
        # Providers return the sessions most recent first: that is the date order.
        self.summaries = self.catalog.list_project_sessions(self.project)
        self.active_ids = {
            summary.session.session_id
            for summary in self.summaries
            if self.catalog.is_active(summary.session)
        }
        invalid_line_count = sum(summary.invalid_line_count for summary in self.summaries)
        if invalid_line_count:
            self.show_note(f"Note: {invalid_line_count} unreadable lines were skipped.")
        self.update_subtitle()

    def rows(self, filter_text: str) -> Iterable[TableRow]:
        for index, summary in enumerate(self.summaries):
            if matches_filter(summary, filter_text):
                yield str(index), self.format_session_row(summary)

    def leave(self) -> None:
        self.app.pop_screen()

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        summary = self.summaries[int(str(event.row_key.value))]
        self.app.push_screen(TranscriptScreen(self.catalog, summary))

    def action_toggle_sort(self) -> None:
        self.session_order = "size" if self.session_order == "date" else "date"
        self.summaries = sort_sessions(self.summaries, self.session_order)
        self.update_subtitle()
        self.show_rows()

    def update_subtitle(self) -> None:
        self.sub_title = f"{format_project_label(self.project)} · sorted by {self.session_order}"

    def format_session_row(self, summary: SessionSummary) -> tuple[str, ...]:
        is_active = summary.session.session_id in self.active_ids
        return (
            ACTIVE_LABEL if is_active else "",
            format_title(summary.title),
            format_moment(summary.started_at, None),
            format_moment(summary.ended_at, None),
            format_size(summary.size_bytes),
        )


def matches_filter(summary: SessionSummary, filter_text: str) -> bool:
    """Case-insensitive match on the title or on the start or end date as shown."""
    needle = filter_text.strip().casefold()
    shown = (
        format_title(summary.title),
        format_moment(summary.started_at, None),
        format_moment(summary.ended_at, None),
    )
    return any(needle in text.casefold() for text in shown)


def sort_sessions(summaries: list[SessionSummary], order: SortOrder) -> list[SessionSummary]:
    """Largest first by size; most recent first by date, with undated sessions last."""
    if order == "size":
        return sorted(summaries, key=lambda summary: summary.size_bytes, reverse=True)
    return sort_most_recent_first(summaries)
