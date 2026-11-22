"""The first screen: every project of every provider, with a text filter."""

from collections.abc import Sequence
from typing import ClassVar

from textual.app import ComposeResult
from textual.binding import Binding, BindingType
from textual.screen import Screen
from textual.widgets import DataTable, Footer, Header, Input, Static

from agent_desk.display import format_moment, format_project_label, format_size
from agent_desk.domain.errors import ProviderNotFound
from agent_desk.services.catalog import CatalogService, ProjectOverview

COLUMNS = ("Provider", "Project", "Sessions", "Last activity", "Size")


class ProjectsScreen(Screen[None]):
    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("slash", "focus_filter", "Filter"),
        Binding("escape", "focus_table", "Back to list", show=False),
    ]

    def __init__(self, catalog: CatalogService) -> None:
        super().__init__()
        self.catalog = catalog
        self.overviews: list[ProjectOverview] = []

    def compose(self) -> ComposeResult:
        yield Header()
        yield Input(placeholder="Filter projects (press /)", id="filter")
        yield DataTable(cursor_type="row", id="projects")
        yield Static(id="note")
        yield Footer()

    def on_mount(self) -> None:
        self.query_one(DataTable).add_columns(*COLUMNS)
        catalog = self.catalog.list_projects()
        self.overviews = catalog.projects
        self.query_one("#note", Static).update(
            describe_notes(catalog.projects, catalog.missing_providers)
        )
        self.show_projects("")
        self.action_focus_table()

    def on_input_changed(self, event: Input.Changed) -> None:
        self.show_projects(event.value)

    def show_projects(self, filter_text: str) -> None:
        table = self.query_one(DataTable)
        table.clear()
        for index, overview in enumerate(self.overviews):
            if matches_filter(overview, filter_text):
                table.add_row(*format_project_row(overview), key=str(index))

    def action_focus_filter(self) -> None:
        self.query_one(Input).focus()

    def action_focus_table(self) -> None:
        self.query_one(DataTable).focus()


def matches_filter(overview: ProjectOverview, filter_text: str) -> bool:
    """Case-insensitive match on the provider or the project label."""
    needle = filter_text.strip().casefold()
    haystack = f"{overview.project.provider_id} {format_project_label(overview.project)}"
    return needle in haystack.casefold()


def format_project_row(overview: ProjectOverview) -> tuple[str, ...]:
    return (
        overview.project.provider_id,
        format_project_label(overview.project),
        str(overview.session_count),
        format_moment(overview.last_activity, None),
        format_size(overview.size_bytes),
    )


def describe_notes(
    projects: Sequence[ProjectOverview], missing_providers: Sequence[ProviderNotFound]
) -> str:
    notes = [
        f"Note: no {item.provider_id} data found at {item.root}." for item in missing_providers
    ]
    if not projects:
        notes.append("No projects found.")
    return "\n".join(notes)
