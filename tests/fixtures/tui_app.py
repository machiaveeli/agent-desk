"""Builds the TUI app for tests that do not resume sessions."""

import time
from collections.abc import Callable
from pathlib import Path

from textual.pilot import Pilot

from agent_desk.services.catalog import CatalogService
from agent_desk.services.resume import ResumeService
from agent_desk.tui.app import AgentDeskApp

# Only a guard against hanging: generous, because CI machines can be slow.
WAIT_LIMIT_SECONDS = 60.0
POLL_SECONDS = 0.01


async def wait_until(pilot: Pilot[None], condition: Callable[[], bool]) -> None:
    """`Pilot.press` may return before a screen it opened is mounted, or a worker it started
    is done. Tests wait for what they need to see instead of assuming a speed."""
    deadline = time.monotonic() + WAIT_LIMIT_SECONDS
    while not condition():
        if time.monotonic() > deadline:
            raise AssertionError("the expected state was not reached in time")
        await pilot.pause(POLL_SECONDS)


def never_launch(argv: list[str], cwd: Path) -> int:
    raise AssertionError("this test must not start a process")


def make_browsing_app(catalog: CatalogService) -> AgentDeskApp:
    """No AI CLI is on PATH and none may be started."""
    return AgentDeskApp(catalog, ResumeService(catalog, lambda name: None, never_launch))
