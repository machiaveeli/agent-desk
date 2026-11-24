"""Pilot tests for the transcript screen, opened with Enter on a session."""

import threading
from collections.abc import Iterator
from dataclasses import dataclass, field

import pytest
from textual.pilot import Pilot
from textual.screen import Screen
from textual.widgets import RichLog, Static

from agent_desk.domain.models import Session, TranscriptEntry
from agent_desk.providers.claude_code import ClaudeCodeProvider
from agent_desk.providers.claude_transcript import read_transcript_entries
from agent_desk.services.catalog import CatalogService
from agent_desk.tui.app import AgentDeskApp
from agent_desk.tui.projects_screen import ProjectsScreen
from agent_desk.tui.sessions_screen import SessionsScreen
from agent_desk.tui.transcript_screen import TranscriptScreen
from fixtures.claude_tree import (
    ClaudeTree,
    assistant_line,
    text_block,
    tool_use_block,
    user_line,
)
from fixtures.tui_app import make_browsing_app, wait_until

SESSION_ID = "00000000-0000-4000-8000-00000000000a"
CWD = "/work/web"
FIVE_MEGABYTES = 5 * 1024 * 1024
WAIT_SECONDS = 60
LOADING_NOTE = "Loading…"
# Wide enough that no transcript line in these tests wraps.
SCREEN_SIZE = (160, 40)


def make_app(claude_tree: ClaudeTree) -> AgentDeskApp:
    return make_browsing_app(CatalogService([ClaudeCodeProvider(root=claude_tree.root)]))


def shown_lines(app: AgentDeskApp) -> list[str]:
    return [strip.text.rstrip() for strip in app.screen.query_one(RichLog).lines]


def note_of(app: AgentDeskApp) -> str:
    return str(app.screen.query_one("#note", Static).render())


def is_ready(app: AgentDeskApp, screen_type: type[Screen[None]]) -> bool:
    return type(app.screen) is screen_type and app.screen.is_mounted


async def open_transcript(app: AgentDeskApp, pilot: Pilot[None]) -> None:
    """From the projects screen, opens the first session of the first project."""
    await wait_until(pilot, lambda: is_ready(app, ProjectsScreen))
    await pilot.press("enter")
    await wait_until(pilot, lambda: is_ready(app, SessionsScreen))
    await open_selected_session(app, pilot)


async def open_selected_session(app: AgentDeskApp, pilot: Pilot[None]) -> None:
    await pilot.press("enter")
    await wait_until(pilot, lambda: is_ready(app, TranscriptScreen))


async def go_back_to_sessions(app: AgentDeskApp, pilot: Pilot[None]) -> None:
    await pilot.press("escape")
    await wait_until(pilot, lambda: is_ready(app, SessionsScreen))


async def wait_for_final_note(app: AgentDeskApp, pilot: Pilot[None]) -> str:
    await wait_until(pilot, lambda: note_of(app) != LOADING_NOTE)
    return note_of(app)


async def test_enter_on_a_session_shows_its_condensed_transcript(
    claude_tree: ClaudeTree,
) -> None:
    project_dir = claude_tree.add_project(CWD)
    lines = [
        user_line("List the files", cwd=CWD),
        assistant_line(
            [text_block("Listing them."), tool_use_block("t1", "Bash", {"command": "ls -la"})],
            cwd=CWD,
        ),
    ]
    claude_tree.add_session(project_dir, SESSION_ID, lines)
    app = make_app(claude_tree)

    async with app.run_test(size=SCREEN_SIZE) as pilot:
        await open_transcript(app, pilot)
        note = await wait_for_final_note(app, pilot)
        shown = shown_lines(app)

    assert shown == ["You: List the files", "Assistant: Listing them.", "  [Bash] ls -la"]
    assert note == "3 entries."


async def test_escape_goes_back_to_the_sessions(claude_tree: ClaudeTree) -> None:
    project_dir = claude_tree.add_project(CWD)
    claude_tree.add_session(project_dir, SESSION_ID, [user_line("hi", cwd=CWD)])
    app = make_app(claude_tree)

    async with app.run_test(size=SCREEN_SIZE) as pilot:
        await open_transcript(app, pilot)
        await go_back_to_sessions(app, pilot)
        back = type(app.screen)

    assert back is SessionsScreen


async def test_a_session_file_that_is_gone_is_reported(claude_tree: ClaudeTree) -> None:
    project_dir = claude_tree.add_project(CWD)
    path = claude_tree.add_session(project_dir, SESSION_ID, [user_line("hi", cwd=CWD)])
    app = make_app(claude_tree)

    async with app.run_test(size=SCREEN_SIZE) as pilot:
        await wait_until(pilot, lambda: is_ready(app, ProjectsScreen))
        await pilot.press("enter")
        await wait_until(pilot, lambda: is_ready(app, SessionsScreen))
        # Deleted by another program while the list is on screen.
        path.unlink()
        await open_selected_session(app, pilot)
        note = await wait_for_final_note(app, pilot)

    assert note == f"Error: could not read {path.name}."


@dataclass(frozen=True)
class HeldBackProvider(ClaudeCodeProvider):
    """The real Claude provider, except that the transcript holds back its last entry until
    `release` is set: a large file whose reading has not finished yet. Without it, whether the
    load is still running when the test looks would depend on the machine's speed."""

    release: threading.Event = field(default_factory=threading.Event)

    def read_transcript(self, session: Session) -> Iterator[TranscriptEntry]:
        *entries, last = super().read_transcript(session)
        yield from entries
        self.release.wait(WAIT_SECONDS)
        yield last


@pytest.mark.slow
async def test_screen_responds_before_a_large_transcript_finishes_loading(
    claude_tree: ClaudeTree,
) -> None:
    project_dir = claude_tree.add_project(CWD)
    path = claude_tree.add_large_session(
        project_dir, SESSION_ID, cwd=CWD, min_size_bytes=FIVE_MEGABYTES
    )
    entry_count = len(list(read_transcript_entries(path)))
    provider = HeldBackProvider(root=claude_tree.root)
    app = make_browsing_app(CatalogService([provider]))

    async with app.run_test(size=SCREEN_SIZE) as pilot:
        await open_transcript(app, pilot)
        while_loading = note_of(app)
        await go_back_to_sessions(app, pilot)
        await open_selected_session(app, pilot)
        provider.release.set()
        when_done = await wait_for_final_note(app, pilot)

    assert while_loading == LOADING_NOTE
    # Opened again and left to finish: every entry arrived, across many batches.
    assert when_done == f"{entry_count} entries."


async def test_entries_that_arrive_after_the_screen_closed_are_ignored(
    claude_tree: ClaudeTree,
) -> None:
    project_dir = claude_tree.add_project(CWD)
    claude_tree.add_session(project_dir, SESSION_ID, [user_line("hi", cwd=CWD)])
    app = make_app(claude_tree)

    async with app.run_test(size=SCREEN_SIZE) as pilot:
        await open_transcript(app, pilot)
        await wait_for_final_note(app, pilot)
        transcript = app.screen
        assert isinstance(transcript, TranscriptScreen)
        await go_back_to_sessions(app, pilot)
        # The worker checked for cancellation just before Escape, then handed these over.
        transcript.show_entries((TranscriptEntry("user", "late"),))
        transcript.show_note("late")

    assert transcript.entry_count == 1
