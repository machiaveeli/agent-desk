"""The Textual app. Screens only call services and render what they return."""

from typing import ClassVar

from textual.app import App
from textual.binding import Binding, BindingType
from textual.widgets import HelpPanel

from agent_desk.services.catalog import CatalogService
from agent_desk.services.resume import ResumeService
from agent_desk.services.trash import TrashService
from agent_desk.tui.projects_screen import ProjectsScreen


class AgentDeskApp(App[None]):
    TITLE = "agent-desk"
    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("q", "quit", "Quit"),
        Binding("question_mark", "toggle_help", "Help"),
    ]

    def __init__(self, catalog: CatalogService, resume: ResumeService, trash: TrashService) -> None:
        super().__init__()
        self.catalog = catalog
        self.resume = resume
        self.trash = trash

    def on_mount(self) -> None:
        self.push_screen(ProjectsScreen(self.catalog, self.resume, self.trash))

    def action_toggle_help(self) -> None:
        if self.screen.query(HelpPanel):
            self.action_hide_help_panel()
        else:
            self.action_show_help_panel()
