"""Builds the TUI app for tests that do not resume sessions."""

import os
import time
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

from textual.message import Message
from textual.notifications import Notify
from textual.pilot import Pilot

from agent_desk.services.catalog import CatalogService
from agent_desk.services.resume import ResumeService
from agent_desk.services.trash import TrashService
from agent_desk.tui.app import AgentDeskApp

# Only a guard against hanging: generous, because CI machines can be slow.
WAIT_LIMIT_SECONDS = 60.0
POLL_SECONDS = 0.01
TRASH_RETENTION_DAYS = 30


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


def make_unusable_trash(catalog: CatalogService) -> TrashService:
    """For tests that never trash: rooted under the null device, so it lists nothing and any
    attempt to store something fails instead of writing somewhere real."""
    return TrashService(
        root=Path(os.devnull) / "trash",
        is_active=catalog.is_active,
        now=lambda: datetime.now(UTC),
        retention_days=TRASH_RETENTION_DAYS,
    )


def make_browsing_app(catalog: CatalogService, trash: TrashService | None = None) -> AgentDeskApp:
    """No AI CLI is on PATH and none may be started."""
    resume = ResumeService(catalog, lambda name: None, never_launch)
    return AgentDeskApp(catalog, resume, trash or make_unusable_trash(catalog))


class NotificationRecorder:
    """Pass as `run_test(message_hook=...)`: keeps every notification and its severity."""

    def __init__(self) -> None:
        self.messages: list[tuple[str, str]] = []

    def __call__(self, message: Message) -> None:
        if isinstance(message, Notify):
            self.messages.append((message.notification.message, message.notification.severity))
