"""Pilot tests for the transcript screen, opened with Enter on a session."""

import threading
from collections.abc import Iterator
from dataclasses import dataclass, field

import pytest
from textual.widgets import RichLog, Static

from agent_desk.domain.models import Session, TranscriptEntry
from agent_desk.providers.claude_code import ClaudeCodeProvider
from agent_desk.providers.claude_transcript import read_transcript_entries
from agent_desk.services.catalog import CatalogService
from agent_desk.tui.app import AgentDeskApp
from agent_desk.tui.sessions_screen import SessionsScreen
from agent_desk.tui.transcript_screen import TranscriptScreen
from fixtures.claude_tree import (
    ClaudeTree,
    assistant_line,
    text_block,
    tool_use_block,
    user_line,
)

SESSION_ID = "00000000-0000-4000-8000-00000000000a"
CWD = "/work/web"
FIVE_MEGABYTES = 5 * 1024 * 1024
WAIT_SECONDS = 10
# Wide enough that no transcript line in these tests wraps.
SCREEN_SIZE = (160, 40)


def make_app(claude_tree: ClaudeTree) -> AgentDeskApp:
    return AgentDeskApp(CatalogService([ClaudeCodeProvider(root=claude_tree.root)]))


def shown_lines(app: AgentDeskApp) -> list[str]:
    return [strip.text.rstrip() for strip in app.screen.query_one(RichLog).lines]


def note_of(app: AgentDeskApp) -> str:
    return str(app.screen.query_one("#note", Static).render())


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
        await pilot.press("enter", "enter")
        await app.workers.wait_for_complete()
        await pilot.pause()
        shown = shown_lines(app)
        note = note_of(app)

    assert shown == ["You: List the files", "Assistant: Listing them.", "  [Bash] ls -la"]
    assert note == "3 entries."


async def test_escape_goes_back_to_the_sessions(claude_tree: ClaudeTree) -> None:
    project_dir = claude_tree.add_project(CWD)
    claude_tree.add_session(project_dir, SESSION_ID, [user_line("hi", cwd=CWD)])
    app = make_app(claude_tree)

    async with app.run_test(size=SCREEN_SIZE) as pilot:
        await pilot.press("enter", "enter")
        opened = app.screen
        await pilot.press("escape")
        back = app.screen

    assert (type(opened), type(back)) == (TranscriptScreen, SessionsScreen)


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
    app = AgentDeskApp(CatalogService([provider]))

    async with app.run_test(size=SCREEN_SIZE) as pilot:
        await pilot.press("enter", "enter")
        while_loading = note_of(app)
        await pilot.press("escape")
        screen_after_escape = type(app.screen)
        await pilot.press("enter")
        provider.release.set()
        await app.workers.wait_for_complete()
        await pilot.pause()
        when_done = note_of(app)

    assert while_loading == "Loading…"
    assert screen_after_escape is SessionsScreen
    # Opened again and left to finish: every entry arrived, across many batches.
    assert when_done == f"{entry_count} entries."
