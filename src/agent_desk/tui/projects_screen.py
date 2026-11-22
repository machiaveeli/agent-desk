"""The first screen: every project of every provider, with a text filter."""

from collections.abc import Iterable, Sequence

from textual.widgets import DataTable

from agent_desk.display import format_moment, format_project_label, format_size
from agent_desk.domain.errors import ProviderNotFound
from agent_desk.services.catalog import CatalogService, ProjectOverview
from agent_desk.tui.sessions_screen import SessionsScreen
from agent_desk.tui.table_screen import TableRow, TableScreen


class ProjectsScreen(TableScreen):
    COLUMNS = ("Provider", "Project", "Sessions", "Last activity", "Size")
    FILTER_PLACEHOLDER = "Filter projects (press /)"

    def __init__(self, catalog: CatalogService) -> None:
        super().__init__()
        self.catalog = catalog
        self.overviews: list[ProjectOverview] = []

    def load(self) -> None:
        catalog = self.catalog.list_projects()
        self.overviews = catalog.projects
        self.show_note(describe_notes(catalog.projects, catalog.missing_providers))

    def rows(self, filter_text: str) -> Iterable[TableRow]:
        for index, overview in enumerate(self.overviews):
            if matches_filter(overview, filter_text):
                yield str(index), format_project_row(overview)

    def leave(self) -> None:
        """The first screen has nowhere to go back to; `q` quits."""

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        overview = self.overviews[int(str(event.row_key.value))]
        self.app.push_screen(SessionsScreen(self.catalog, overview.project))


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
