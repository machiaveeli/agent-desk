"""Pilot tests: trashing sessions from the sessions screen and restoring them from the trash."""

from datetime import UTC, datetime
from pathlib import Path

import pytest
from textual.widgets import DataTable, Static

from agent_desk.domain.models import TrashEntry
from agent_desk.providers.claude_code import ClaudeCodeProvider
from agent_desk.providers.processes import NOT_RUNNING, ProcessState
from agent_desk.services.catalog import CatalogService
from agent_desk.services.trash import TrashService
from agent_desk.tui.app import AgentDeskApp
from agent_desk.tui.confirm_screen import ConfirmScreen
from agent_desk.tui.projects_screen import ProjectsScreen
from agent_desk.tui.sessions_screen import SessionsScreen
from agent_desk.tui.trash_screen import TrashScreen
from fixtures.claude_tree import FAKE_PROC_START, ClaudeTree, custom_title_line, user_line
from fixtures.file_tree import snapshot
from fixtures.tui_app import NotificationRecorder, make_browsing_app, wait_until

FIRST_ID = "00000000-0000-4000-8000-00000000000a"
SECOND_ID = "00000000-0000-4000-8000-00000000000b"
CWD = "/work/web"
NOW = datetime(2026, 11, 23, 14, 5, 12, tzinfo=UTC)
RETENTION_DAYS = 30
PID = 4242
STATE_COLUMN = 0
TITLE_COLUMN = 1
SESSIONS_COLUMN = 2
TRASH_TITLE_COLUMN = 5


@pytest.fixture
def trash_root(tmp_path: Path) -> Path:
    return tmp_path / "data" / "trash"


def make_app(
    claude_tree: ClaudeTree, trash_root: Path, running: ProcessState = NOT_RUNNING
) -> AgentDeskApp:
    provider = ClaudeCodeProvider(
        root=claude_tree.root, inspect_process=lambda pid: running if pid == PID else NOT_RUNNING
    )
    catalog = CatalogService([provider])
    trash = TrashService(
        root=trash_root, is_active=catalog.is_active, now=lambda: NOW, retention_days=RETENTION_DAYS
    )
    return make_browsing_app(catalog, trash)


def add_sessions(claude_tree: ClaudeTree) -> None:
    """ "First" is the most recent, so it is the row selected when the screen opens."""
    project_dir = claude_tree.add_project(CWD)
    for session_id, title, minute in [(FIRST_ID, "First", 20), (SECOND_ID, "Second", 10)]:
        lines = [custom_title_line(title), user_line("hi", cwd=CWD, minute=minute)]
        claude_tree.add_session(project_dir, session_id, lines)


def column(app: AgentDeskApp, index: int) -> list[str]:
    table = app.screen.query_one(DataTable)
    return [str(table.get_row_at(row)[index]) for row in range(table.row_count)]


def trashed_titles(app: AgentDeskApp) -> list[str]:
    return sorted(listed.entry.title for listed in app.trash.list_entries().entries)


async def test_d_then_yes_moves_the_selected_session_to_the_trash(
    claude_tree: ClaudeTree, trash_root: Path
) -> None:
    add_sessions(claude_tree)
    app = make_app(claude_tree, trash_root)
    notifications = NotificationRecorder()

    async with app.run_test(message_hook=notifications) as pilot:
        await pilot.press("enter", "d")
        await wait_until(pilot, lambda: isinstance(app.screen, ConfirmScreen))
        await pilot.press("y")
        await wait_until(pilot, lambda: isinstance(app.screen, SessionsScreen))
        titles = column(app, TITLE_COLUMN)

    assert titles == ["Second"]
    assert trashed_titles(app) == ["First"]
    assert notifications.messages == [("Moved 1 sessions to the trash.", "information")]


async def test_d_then_no_changes_nothing(claude_tree: ClaudeTree, trash_root: Path) -> None:
    add_sessions(claude_tree)
    app = make_app(claude_tree, trash_root)
    before = snapshot(claude_tree.root)

    async with app.run_test() as pilot:
        await pilot.press("enter", "d")
        await wait_until(pilot, lambda: isinstance(app.screen, ConfirmScreen))
        await pilot.press("n")
        await wait_until(pilot, lambda: isinstance(app.screen, SessionsScreen))
        titles = column(app, TITLE_COLUMN)

    assert titles == ["First", "Second"]
    assert (snapshot(claude_tree.root), trash_root.exists()) == (before, False)


async def test_space_marks_sessions_and_d_asks_about_all_of_them(
    claude_tree: ClaudeTree, trash_root: Path
) -> None:
    add_sessions(claude_tree)
    app = make_app(claude_tree, trash_root)

    async with app.run_test() as pilot:
        await pilot.press("enter", "space", "down", "space")
        states = column(app, STATE_COLUMN)
        await pilot.press("d")
        await wait_until(pilot, lambda: isinstance(app.screen, ConfirmScreen))
        question = str(app.screen.query(Static).first().render())
        await pilot.press("y")
        await wait_until(pilot, lambda: isinstance(app.screen, SessionsScreen))
        titles = column(app, TITLE_COLUMN)

    assert states == ["✓", "✓"]
    assert "Move 2 sessions to the trash?" in question
    assert ("  First" in question, "  Second" in question) == (True, True)
    assert (titles, trashed_titles(app)) == ([], ["First", "Second"])


async def test_space_twice_unmarks_the_session(claude_tree: ClaudeTree, trash_root: Path) -> None:
    add_sessions(claude_tree)
    app = make_app(claude_tree, trash_root)

    async with app.run_test() as pilot:
        await pilot.press("enter", "space", "space")
        states = column(app, STATE_COLUMN)

    assert states == ["", ""]


async def test_an_open_session_is_refused_with_a_warning_and_nothing_moves(
    claude_tree: ClaudeTree, trash_root: Path
) -> None:
    add_sessions(claude_tree)
    claude_tree.add_active_session_file(pid=PID, session_id=FIRST_ID, cwd=CWD)
    running = ProcessState(is_running=True, start_marker=FAKE_PROC_START)
    app = make_app(claude_tree, trash_root, running)
    notifications = NotificationRecorder()
    before = snapshot(claude_tree.root)

    async with app.run_test(message_hook=notifications) as pilot:
        await pilot.press("enter", "d")
        await pilot.pause()
        screen = app.screen

    assert isinstance(screen, SessionsScreen)
    assert notifications.messages == [
        ("Skipped 1 open sessions: close them before moving them to the trash.", "warning")
    ]
    assert (snapshot(claude_tree.root), trash_root.exists()) == (before, False)


async def test_marked_open_sessions_are_left_out_and_the_rest_is_asked_about(
    claude_tree: ClaudeTree, trash_root: Path
) -> None:
    add_sessions(claude_tree)
    claude_tree.add_active_session_file(pid=PID, session_id=FIRST_ID, cwd=CWD)
    running = ProcessState(is_running=True, start_marker=FAKE_PROC_START)
    app = make_app(claude_tree, trash_root, running)

    async with app.run_test() as pilot:
        await pilot.press("enter", "space", "down", "space", "d")
        await wait_until(pilot, lambda: isinstance(app.screen, ConfirmScreen))
        question = str(app.screen.query(Static).first().render())
        await pilot.press("y")
        await wait_until(pilot, lambda: isinstance(app.screen, SessionsScreen))

    assert "Move 1 sessions to the trash?" in question
    assert trashed_titles(app) == ["Second"]


async def test_trash_then_restore_from_the_trash_screen_brings_the_session_back(
    claude_tree: ClaudeTree, trash_root: Path
) -> None:
    add_sessions(claude_tree)
    app = make_app(claude_tree, trash_root)
    notifications = NotificationRecorder()
    before = snapshot(claude_tree.root)

    async with app.run_test(message_hook=notifications) as pilot:
        await pilot.press("enter", "d")
        await wait_until(pilot, lambda: isinstance(app.screen, ConfirmScreen))
        await pilot.press("y")
        await wait_until(pilot, lambda: isinstance(app.screen, SessionsScreen))
        await pilot.press("escape")
        await wait_until(pilot, lambda: isinstance(app.screen, ProjectsScreen))
        count_after_trash = column(app, SESSIONS_COLUMN)
        await pilot.press("t")
        await wait_until(pilot, lambda: isinstance(app.screen, TrashScreen))
        trash_titles = column(app, TRASH_TITLE_COLUMN)
        await pilot.press("u")
        await pilot.pause()
        trash_titles_after_restore = column(app, TRASH_TITLE_COLUMN)
        await pilot.press("escape")
        await wait_until(pilot, lambda: isinstance(app.screen, ProjectsScreen))
        count_after_restore = column(app, SESSIONS_COLUMN)

    assert (count_after_trash, count_after_restore) == (["1"], ["2"])
    assert (trash_titles, trash_titles_after_restore) == (["First"], [])
    assert notifications.messages[-1] == ("Restored 'First'.", "information")
    assert snapshot(claude_tree.root) == before


async def test_the_trash_screen_says_when_it_is_empty(
    claude_tree: ClaudeTree, trash_root: Path
) -> None:
    add_sessions(claude_tree)
    app = make_app(claude_tree, trash_root)

    async with app.run_test() as pilot:
        await pilot.press("t")
        await wait_until(pilot, lambda: isinstance(app.screen, TrashScreen))
        note = str(app.screen.query_one("#note", Static).render())

    assert note == "The trash is empty."


async def test_restore_refusal_is_shown_and_the_entry_stays(
    claude_tree: ClaudeTree, trash_root: Path
) -> None:
    add_sessions(claude_tree)
    app = make_app(claude_tree, trash_root)
    notifications = NotificationRecorder()

    async with app.run_test(message_hook=notifications) as pilot:
        await pilot.press("enter", "d")
        await wait_until(pilot, lambda: isinstance(app.screen, ConfirmScreen))
        await pilot.press("y")
        await wait_until(pilot, lambda: isinstance(app.screen, SessionsScreen))
        [listed] = app.trash.list_entries().entries
        entry: TrashEntry = listed.entry
        entry.items[0].original_path.write_bytes(b"a new file in the way\n")
        await pilot.press("escape", "t")
        await wait_until(pilot, lambda: isinstance(app.screen, TrashScreen))
        await pilot.press("u")
        await pilot.pause()
        trash_titles = column(app, TRASH_TITLE_COLUMN)

    assert trash_titles == ["First"]
    assert notifications.messages[-1][1] == "error"
    assert notifications.messages[-1][0].startswith("Cannot restore: ")


class Processes:
    """The process table the Claude provider sees; a test can start a session meanwhile."""

    def __init__(self) -> None:
        self.state = NOT_RUNNING

    def inspect(self, pid: int) -> ProcessState:
        return self.state if pid == PID else NOT_RUNNING

    def start(self, claude_tree: ClaudeTree, session_id: str) -> None:
        claude_tree.add_active_session_file(pid=PID, session_id=session_id, cwd=CWD)
        self.state = ProcessState(is_running=True, start_marker=FAKE_PROC_START)


def make_app_with_processes(
    claude_tree: ClaudeTree, trash_root: Path, processes: Processes
) -> AgentDeskApp:
    catalog = CatalogService([ClaudeCodeProvider(claude_tree.root, processes.inspect)])
    trash = TrashService(
        root=trash_root, is_active=catalog.is_active, now=lambda: NOW, retention_days=RETENTION_DAYS
    )
    return make_browsing_app(catalog, trash)


async def test_a_session_opened_after_the_list_was_read_is_refused_by_the_trash(
    claude_tree: ClaudeTree, trash_root: Path
) -> None:
    add_sessions(claude_tree)
    processes = Processes()
    app = make_app_with_processes(claude_tree, trash_root, processes)
    notifications = NotificationRecorder()

    async with app.run_test(message_hook=notifications) as pilot:
        await pilot.press("enter")
        processes.start(claude_tree, FIRST_ID)
        await pilot.press("d")
        await wait_until(pilot, lambda: isinstance(app.screen, ConfirmScreen))
        await pilot.press("y")
        await wait_until(pilot, lambda: isinstance(app.screen, SessionsScreen))
        await pilot.pause()

    assert notifications.messages == [
        (
            "Cannot trash 'First': the session is still open; close it before moving it to "
            "the trash.",
            "error",
        )
    ]
    assert trashed_titles(app) == []


async def test_marks_are_cleared_after_trashing_even_for_a_refused_session(
    claude_tree: ClaudeTree, trash_root: Path
) -> None:
    add_sessions(claude_tree)
    processes = Processes()
    app = make_app_with_processes(claude_tree, trash_root, processes)

    async with app.run_test() as pilot:
        await pilot.press("enter", "space", "down", "space")
        processes.start(claude_tree, FIRST_ID)
        await pilot.press("d")
        await wait_until(pilot, lambda: isinstance(app.screen, ConfirmScreen))
        await pilot.press("y")
        await wait_until(pilot, lambda: isinstance(app.screen, SessionsScreen))
        await pilot.pause()
        rows = list(zip(column(app, STATE_COLUMN), column(app, TITLE_COLUMN), strict=True))

    assert rows == [("active", "First")]
    assert trashed_titles(app) == ["Second"]
