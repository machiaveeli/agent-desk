"""The sessions of one project, sortable by date or size, with a title and date filter."""

from collections.abc import Iterable
from pathlib import Path
from typing import ClassVar, Literal

from textual.app import SuspendNotSupported
from textual.binding import Binding, BindingType
from textual.coordinate import Coordinate
from textual.widgets import DataTable

from agent_desk.display import format_moment, format_project_label, format_size, format_title
from agent_desk.domain.errors import ResumeError, TrashError
from agent_desk.domain.models import Project, SessionSummary
from agent_desk.services.catalog import CatalogService, sort_most_recent_first
from agent_desk.services.resume import ResumePlan, ResumeService
from agent_desk.services.trash import TrashService
from agent_desk.tui.confirm_screen import ConfirmScreen
from agent_desk.tui.table_screen import TableRow, TableScreen
from agent_desk.tui.transcript_screen import TranscriptScreen

type SortOrder = Literal["date", "size"]

ACTIVE_LABEL = "active"
MARK_LABEL = "✓"
# The confirmation lists at most this many titles, so the dialog fits on screen.
MAX_TITLES_IN_QUESTION = 8
ACTIVE_SESSION_QUESTION = (
    "This session is open in another terminal. Two copies may overwrite each other.\n\n"
    "Resume it anyway?"
)
CANNOT_SUSPEND_MESSAGE = (
    "Cannot resume here: this terminal cannot be handed over to another program."
)


class SessionsScreen(TableScreen):
    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("s", "toggle_sort", "Sort by date/size"),
        Binding("r", "resume", "Resume"),
        Binding("space", "toggle_mark", "Mark"),
        Binding("d", "trash", "Trash"),
    ]
    COLUMNS = ("State", "Title", "Started", "Ended", "Size")
    FILTER_PLACEHOLDER = "Filter by title or date, e.g. 2026-01 (press /)"

    def __init__(
        self, catalog: CatalogService, resume: ResumeService, trash: TrashService, project: Project
    ) -> None:
        super().__init__()
        self.catalog = catalog
        self.resume = resume
        self.trash = trash
        self.project = project
        self.summaries: list[SessionSummary] = []
        self.active_ids: set[str] = set()
        self.marked_ids: set[str] = set()
        self.session_order: SortOrder = "date"

    def load(self) -> None:
        self.summaries = sort_sessions(
            self.catalog.list_project_sessions(self.project), self.session_order
        )
        self.active_ids = {
            summary.session.session_id
            for summary in self.summaries
            if self.catalog.is_active(summary.session)
        }
        invalid_line_count = sum(summary.invalid_line_count for summary in self.summaries)
        note = f"Note: {invalid_line_count} unreadable lines were skipped."
        self.show_note(note if invalid_line_count else "")
        self.update_subtitle()

    def rows(self, filter_text: str) -> Iterable[TableRow]:
        for index, summary in enumerate(self.summaries):
            if matches_filter(summary, filter_text):
                yield str(index), self.format_session_row(summary)

    def leave(self) -> None:
        # dismiss, not pop_screen: the projects screen reloads in its callback.
        self.dismiss()

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        summary = self.summaries[int(str(event.row_key.value))]
        self.app.push_screen(TranscriptScreen(self.catalog, summary))

    def action_resume(self) -> None:
        summary = self.selected_summary()
        if summary is None:
            return
        plan = self.resume.prepare(summary.session.session_id)
        if isinstance(plan, ResumeError):
            self.notify(f"Cannot resume: {plan.detail}", severity="error", markup=False)
            return
        if not plan.is_active:
            self.launch(plan, summary.session.session_id)
            return

        def launch_if_confirmed(is_confirmed: bool | None) -> None:
            if is_confirmed:
                self.launch(plan, summary.session.session_id)

        self.app.push_screen(ConfirmScreen(ACTIVE_SESSION_QUESTION), launch_if_confirmed)

    def launch(self, plan: ResumePlan, session_id: str) -> None:
        """Hands the terminal to the AI CLI until it exits, then shows the list again with the
        same session selected: the CLI may have changed it, or others, meanwhile."""
        try:
            with self.app.suspend():
                exit_code = self.resume.launch_plan(plan)
        except SuspendNotSupported:
            self.notify(CANNOT_SUSPEND_MESSAGE, severity="error", markup=False)
            return
        if exit_code != 0:
            name = Path(plan.argv[0]).stem
            self.notify(f"{name} exited with code {exit_code}.", severity="warning", markup=False)
        self.load()
        self.show_rows()
        self.select_session(session_id)

    def selected_summary(self) -> SessionSummary | None:
        table = self.query_one(DataTable)
        if table.row_count == 0:
            return None
        row_key = table.coordinate_to_cell_key(Coordinate(table.cursor_row, 0)).row_key
        return self.summaries[int(str(row_key.value))]

    def select_session(self, session_id: str) -> None:
        """Does nothing when the session is gone or hidden by the filter."""
        table = self.query_one(DataTable)
        for index, summary in enumerate(self.summaries):
            if summary.session.session_id == session_id and str(index) in table.rows:
                table.move_cursor(row=table.get_row_index(str(index)))
                return

    def action_toggle_mark(self) -> None:
        summary = self.selected_summary()
        if summary is None:
            return
        session_id = summary.session.session_id
        self.marked_ids.symmetric_difference_update({session_id})
        self.show_rows()
        self.select_session(session_id)

    def action_trash(self) -> None:
        """Trashes the marked sessions, or the selected one when none is marked. Open sessions
        are left out with a warning; the rest go only after a yes."""
        targets = self.trash_targets()
        open_count = sum(summary.session.session_id in self.active_ids for summary in targets)
        if open_count:
            self.notify(
                f"Skipped {open_count} open sessions: close them before moving them to the trash.",
                severity="warning",
                markup=False,
            )
        to_trash = [
            summary for summary in targets if summary.session.session_id not in self.active_ids
        ]
        if not to_trash:
            return

        def trash_if_confirmed(is_confirmed: bool | None) -> None:
            if is_confirmed:
                self.move_to_trash(to_trash)

        self.app.push_screen(ConfirmScreen(describe_trash_question(to_trash)), trash_if_confirmed)

    def trash_targets(self) -> list[SessionSummary]:
        marked = [
            summary for summary in self.summaries if summary.session.session_id in self.marked_ids
        ]
        if marked:
            return marked
        selected = self.selected_summary()
        return [] if selected is None else [selected]

    def move_to_trash(self, summaries: list[SessionSummary]) -> None:
        moved = 0
        for summary in summaries:
            result = self.trash.trash(summary)
            if isinstance(result, TrashError):
                title = format_title(summary.title)
                self.notify(
                    f"Cannot trash '{title}': {result.detail}", severity="error", markup=False
                )
                continue
            moved += 1
        if moved:
            self.notify(f"Moved {moved} sessions to the trash.", markup=False)
        self.marked_ids.clear()
        self.load()
        self.show_rows()

    def action_toggle_sort(self) -> None:
        self.session_order = "size" if self.session_order == "date" else "date"
        self.summaries = sort_sessions(self.summaries, self.session_order)
        self.update_subtitle()
        self.show_rows()

    def update_subtitle(self) -> None:
        self.sub_title = f"{format_project_label(self.project)} · sorted by {self.session_order}"

    def format_session_row(self, summary: SessionSummary) -> tuple[str, ...]:
        session_id = summary.session.session_id
        state = [MARK_LABEL] if session_id in self.marked_ids else []
        state += [ACTIVE_LABEL] if session_id in self.active_ids else []
        return (
            " ".join(state),
            format_title(summary.title),
            format_moment(summary.started_at, None),
            format_moment(summary.ended_at, None),
            format_size(summary.size_bytes),
        )


def describe_trash_question(summaries: list[SessionSummary]) -> str:
    titles = [f"  {format_title(summary.title)}" for summary in summaries[:MAX_TITLES_IN_QUESTION]]
    hidden = len(summaries) - MAX_TITLES_IN_QUESTION
    if hidden > 0:
        titles.append(f"  and {hidden} more")
    return (
        f"Move {len(summaries)} sessions to the trash?\n\n"
        + "\n".join(titles)
        + "\n\nThey can be restored from the trash (t on the projects screen)."
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
