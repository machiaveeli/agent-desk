"""Builds the TUI app for tests that do not resume sessions."""

from pathlib import Path

from agent_desk.services.catalog import CatalogService
from agent_desk.services.resume import ResumeService
from agent_desk.tui.app import AgentDeskApp


def never_launch(argv: list[str], cwd: Path) -> int:
    raise AssertionError("this test must not start a process")


def make_browsing_app(catalog: CatalogService) -> AgentDeskApp:
    """No AI CLI is on PATH and none may be started."""
    return AgentDeskApp(catalog, ResumeService(catalog, lambda name: None, never_launch))
