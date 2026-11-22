"""Resuming a session with `r` on the sessions screen. A recording launcher stands in for the
AI CLI, so no real process starts."""

import os
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from textual.coordinate import Coordinate
from textual.drivers.headless_driver import HeadlessDriver
from textual.message import Message
from textual.notifications import Notify
from textual.widgets import DataTable

from agent_desk.providers.base import Provider
from agent_desk.providers.claude_code import ClaudeCodeProvider
from agent_desk.providers.codex import CodexProvider
from agent_desk.services.catalog import CatalogService
from agent_desk.services.resume import ResumeService
from agent_desk.tui.app import AgentDeskApp
from agent_desk.tui.confirm_screen import ConfirmScreen
from agent_desk.tui.sessions_screen import SessionsScreen
from fixtures.claude_tree import ClaudeTree, custom_title_line, user_line
from fixtures.codex_tree import CodexTree, user_message

SESSION_A = "00000000-0000-4000-8000-00000000000a"
SESSION_B = "00000000-0000-4000-8000-00000000000b"
SESSION_C = "00000000-0000-4000-8000-00000000000c"
CODEX_SESSION = "00000000-0000-4000-8000-0000000000c1"
CLAUDE_PATH = "/fake/bin/claude"
CODEX_PATH = "/fake/bin/codex"
CODEX_CREATED = datetime(2026, 1, 1, 10, 0, 0)
MODIFIED_AT = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
TITLE_COLUMN = 1
FAILED_EXIT_CODE = 3

type SideEffect = Callable[[], None]


class RecordingLauncher:
    """Mimics `run_in_foreground`: runs the argv in the cwd, waits, returns the exit code."""

    def __init__(self, exit_code: int = 0, side_effect: SideEffect | None = None) -> None:
        self.calls: list[tuple[list[str], Path]] = []
        self.exit_code = exit_code
        self.side_effect = side_effect

    def __call__(self, argv: list[str], cwd: Path) -> int:
        self.calls.append((argv, cwd))
        if self.side_effect is not None:
            self.side_effect()
        return self.exit_code


@pytest.fixture
def terminal_can_be_handed_over(monkeypatch: pytest.MonkeyPatch) -> None:
    """The headless test driver says it cannot suspend, as real Linux and Windows terminals
    can. Here it says it can, and handing the terminal over and back does nothing; the rest
    of Textual's `App.suspend()` runs as it is."""
    monkeypatch.setattr(HeadlessDriver, "can_suspend", property(lambda driver: True))
    monkeypatch.setattr(HeadlessDriver, "suspend_application_mode", lambda driver: None)
    monkeypatch.setattr(HeadlessDriver, "resume_application_mode", lambda driver: None)


@pytest.fixture
def cwd(tmp_path: Path) -> Path:
    path = tmp_path / "work" / "app"
    path.mkdir(parents=True)
    return path


class NotificationRecorder:
    def __init__(self) -> None:
        self.messages: list[tuple[str, str]] = []

    def __call__(self, message: Message) -> None:
        if isinstance(message, Notify):
            self.messages.append((message.notification.message, message.notification.severity))


def make_app(
    providers: list[Provider], launcher: RecordingLauncher, executables: dict[str, str]
) -> AgentDeskApp:
    catalog = CatalogService(providers)
    return AgentDeskApp(catalog, ResumeService(catalog, executables.get, launcher))


def make_claude_app(
    claude_tree: ClaudeTree,
    launcher: RecordingLauncher,
    executables: dict[str, str] | None = None,
) -> AgentDeskApp:
    found = {"claude": CLAUDE_PATH} if executables is None else executables
    return make_app([ClaudeCodeProvider(root=claude_tree.root)], launcher, found)


def add_claude_session(claude_tree: ClaudeTree, cwd: Path, session_id: str, minute: int) -> None:
    lines = [custom_title_line(session_id), user_line("hi", cwd=str(cwd), minute=minute)]
    claude_tree.add_session(claude_tree.add_project(str(cwd)), session_id, lines)


def add_two_claude_sessions(claude_tree: ClaudeTree, cwd: Path) -> None:
    """Listed B then A: A is the second row."""
    add_claude_session(claude_tree, cwd, SESSION_A, minute=1)
    add_claude_session(claude_tree, cwd, SESSION_B, minute=2)


def selected_title(app: AgentDeskApp) -> str:
    table = app.screen.query_one(DataTable)
    return str(table.get_cell_at(Coordinate(table.cursor_row, TITLE_COLUMN)))


def shown_titles(app: AgentDeskApp) -> list[str]:
    table = app.screen.query_one(DataTable)
    return [str(table.get_row_at(row)[TITLE_COLUMN]) for row in range(table.row_count)]


def row_count(app: AgentDeskApp) -> int:
    return app.screen.query_one(DataTable).row_count


async def test_r_resumes_the_selected_session_and_comes_back_to_it(
    terminal_can_be_handed_over: None, claude_tree: ClaudeTree, cwd: Path
) -> None:
    add_two_claude_sessions(claude_tree, cwd)
    launcher = RecordingLauncher()
    app = make_claude_app(claude_tree, launcher)

    async with app.run_test() as pilot:
        await pilot.press("enter", "down", "r")
        await pilot.pause()
        screen = type(app.screen)
        selected = selected_title(app)

    assert launcher.calls == [([CLAUDE_PATH, "--resume", SESSION_A], cwd)]
    assert (screen, selected) == (SessionsScreen, SESSION_A)


async def test_the_list_is_reloaded_after_resuming_and_keeps_the_selection(
    terminal_can_be_handed_over: None, claude_tree: ClaudeTree, cwd: Path
) -> None:
    add_two_claude_sessions(claude_tree, cwd)
    # Another session shows up while the AI CLI runs; it is the newest, so it goes on top.
    launcher = RecordingLauncher(
        side_effect=lambda: add_claude_session(claude_tree, cwd, SESSION_C, minute=3)
    )
    app = make_claude_app(claude_tree, launcher)

    async with app.run_test() as pilot:
        await pilot.press("enter", "down", "r")
        await pilot.pause()
        rows = row_count(app)
        selected = selected_title(app)

    assert (rows, selected) == (3, SESSION_A)


async def test_a_failed_exit_code_is_reported(
    terminal_can_be_handed_over: None, claude_tree: ClaudeTree, cwd: Path
) -> None:
    add_two_claude_sessions(claude_tree, cwd)
    notifications = NotificationRecorder()
    app = make_claude_app(claude_tree, RecordingLauncher(exit_code=FAILED_EXIT_CODE))

    async with app.run_test(message_hook=notifications) as pilot:
        await pilot.press("enter", "r")
        await pilot.pause()

    assert notifications.messages == [(f"claude exited with code {FAILED_EXIT_CODE}.", "warning")]


async def test_a_missing_project_folder_is_refused_with_a_message(
    terminal_can_be_handed_over: None, claude_tree: ClaudeTree, tmp_path: Path
) -> None:
    gone = tmp_path / "gone"
    add_claude_session(claude_tree, gone, SESSION_A, minute=1)
    launcher = RecordingLauncher()
    notifications = NotificationRecorder()
    app = make_claude_app(claude_tree, launcher)

    async with app.run_test(message_hook=notifications) as pilot:
        await pilot.press("enter", "r")
        await pilot.pause()

    assert launcher.calls == []
    assert notifications.messages == [
        (f"Cannot resume: the project folder {gone} no longer exists.", "error")
    ]


async def test_a_missing_cli_is_refused_with_a_message(
    terminal_can_be_handed_over: None, claude_tree: ClaudeTree, cwd: Path
) -> None:
    add_two_claude_sessions(claude_tree, cwd)
    launcher = RecordingLauncher()
    notifications = NotificationRecorder()
    app = make_claude_app(claude_tree, launcher, executables={})

    async with app.run_test(message_hook=notifications) as pilot:
        await pilot.press("enter", "r")
        await pilot.pause()

    assert launcher.calls == []
    assert notifications.messages == [
        ("Cannot resume: 'claude' is not installed or not on PATH.", "error")
    ]


async def test_a_terminal_that_cannot_be_handed_over_is_reported(
    claude_tree: ClaudeTree, cwd: Path
) -> None:
    add_two_claude_sessions(claude_tree, cwd)
    launcher = RecordingLauncher()
    notifications = NotificationRecorder()
    app = make_claude_app(claude_tree, launcher)

    async with app.run_test(message_hook=notifications) as pilot:
        await pilot.press("enter", "r")
        await pilot.pause()

    assert launcher.calls == []
    assert notifications.messages == [
        ("Cannot resume here: this terminal cannot be handed over to another program.", "error")
    ]


def make_active_codex_app(
    codex_tree: CodexTree, cwd: Path, launcher: RecordingLauncher
) -> AgentDeskApp:
    lines = [user_message("hello")]
    path = codex_tree.add_session(CODEX_SESSION, cwd=str(cwd), created=CODEX_CREATED, lines=lines)
    os.utime(path, (MODIFIED_AT.timestamp(), MODIFIED_AT.timestamp()))
    provider = CodexProvider(root=codex_tree.root, now=lambda: MODIFIED_AT + timedelta(minutes=1))
    return make_app([provider], launcher, {"codex": CODEX_PATH})


async def test_an_active_session_asks_first_and_no_cancels(
    terminal_can_be_handed_over: None, codex_tree: CodexTree, cwd: Path
) -> None:
    launcher = RecordingLauncher()
    app = make_active_codex_app(codex_tree, cwd, launcher)

    async with app.run_test() as pilot:
        await pilot.press("enter", "r")
        asked = type(app.screen)
        await pilot.press("n")
        await pilot.pause()
        back = type(app.screen)

    assert launcher.calls == []
    assert (asked, back) == (ConfirmScreen, SessionsScreen)


async def test_an_active_session_is_resumed_after_yes(
    terminal_can_be_handed_over: None, codex_tree: CodexTree, cwd: Path
) -> None:
    launcher = RecordingLauncher()
    app = make_active_codex_app(codex_tree, cwd, launcher)

    async with app.run_test() as pilot:
        await pilot.press("enter", "r", "y")
        await pilot.pause()
        back = type(app.screen)

    assert launcher.calls == [([CODEX_PATH, "resume", CODEX_SESSION], cwd)]
    assert back is SessionsScreen


async def test_the_reloaded_list_keeps_the_size_order(
    terminal_can_be_handed_over: None, claude_tree: ClaudeTree, cwd: Path
) -> None:
    project_dir = claude_tree.add_project(str(cwd))
    # A is older but larger, so size order (A, B) is the reverse of date order (B, A).
    big = [custom_title_line(SESSION_A), user_line("x" * 3000, cwd=str(cwd), minute=1)]
    claude_tree.add_session(project_dir, SESSION_A, big)
    add_claude_session(claude_tree, cwd, SESSION_B, minute=2)
    app = make_claude_app(claude_tree, RecordingLauncher())

    async with app.run_test() as pilot:
        await pilot.press("enter", "s", "r")
        await pilot.pause()
        titles = shown_titles(app)

    assert titles == [SESSION_A, SESSION_B]
