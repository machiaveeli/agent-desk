"""Pilot tests for the sessions screen, opened with Enter on a project."""

import os
from datetime import UTC, datetime, timedelta

from textual.widgets import DataTable, Static

from agent_desk.providers.claude_code import ClaudeCodeProvider
from agent_desk.providers.codex import CodexProvider
from agent_desk.services.catalog import CatalogService
from agent_desk.tui.app import AgentDeskApp
from agent_desk.tui.projects_screen import ProjectsScreen
from agent_desk.tui.sessions_screen import SessionsScreen
from fixtures.claude_tree import CORRUPTED_LINE, ClaudeTree, custom_title_line, user_line
from fixtures.codex_tree import CodexTree, user_message

SESSION_OLD = "00000000-0000-4000-8000-00000000000a"
SESSION_NEW = "00000000-0000-4000-8000-00000000000b"
SESSION_MID = "00000000-0000-4000-8000-00000000000c"
CODEX_SESSION = "00000000-0000-4000-8000-0000000000c1"
CWD = "/work/web"
CODEX_CREATED = datetime(2026, 1, 1, 10, 0, 0)
MODIFIED_AT = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
# Noon UTC keeps the same calendar day in every timezone from UTC-11 to UTC+11.
NOON_DAY_ONE = 120
NOON_DAY_TWO = 24 * 60 + 120
NOON_DAY_THREE = 2 * 24 * 60 + 120
TITLE_COLUMN = 1
STATE_COLUMN = 0


def make_app(claude_tree: ClaudeTree) -> AgentDeskApp:
    return AgentDeskApp(CatalogService([ClaudeCodeProvider(root=claude_tree.root)]))


def add_three_sessions(claude_tree: ClaudeTree) -> None:
    """Oldest is the largest and newest the smallest, so date and size orders differ."""
    project_dir = claude_tree.add_project(CWD)
    sessions = [
        (SESSION_OLD, "Old big", NOON_DAY_ONE, "x" * 3000),
        (SESSION_MID, "Mid medium", NOON_DAY_TWO, "x" * 1000),
        (SESSION_NEW, "New small", NOON_DAY_THREE, "x"),
    ]
    for session_id, title, minute, prompt in sessions:
        lines = [custom_title_line(title), user_line(prompt, cwd=CWD, minute=minute)]
        claude_tree.add_session(project_dir, session_id, lines)


def column(app: AgentDeskApp, index: int) -> list[str]:
    table = app.screen.query_one(DataTable)
    return [str(table.get_row_at(row)[index]) for row in range(table.row_count)]


async def test_enter_on_a_project_lists_its_sessions_most_recent_first(
    claude_tree: ClaudeTree,
) -> None:
    add_three_sessions(claude_tree)
    app = make_app(claude_tree)

    async with app.run_test() as pilot:
        await pilot.press("enter")
        titles = column(app, TITLE_COLUMN)

    assert titles == ["New small", "Mid medium", "Old big"]


async def test_s_switches_between_size_and_date_order(claude_tree: ClaudeTree) -> None:
    add_three_sessions(claude_tree)
    app = make_app(claude_tree)

    async with app.run_test() as pilot:
        await pilot.press("enter", "s")
        by_size = column(app, TITLE_COLUMN)
        await pilot.press("s")
        by_date = column(app, TITLE_COLUMN)

    assert by_size == ["Old big", "Mid medium", "New small"]
    assert by_date == ["New small", "Mid medium", "Old big"]


async def test_filter_matches_the_title_ignoring_case(claude_tree: ClaudeTree) -> None:
    add_three_sessions(claude_tree)
    app = make_app(claude_tree)

    async with app.run_test() as pilot:
        await pilot.press("enter", "slash", *"mid MEDIUM")
        titles = column(app, TITLE_COLUMN)

    assert titles == ["Mid medium"]


async def test_filter_matches_the_start_or_end_date(claude_tree: ClaudeTree) -> None:
    add_three_sessions(claude_tree)
    app = make_app(claude_tree)

    async with app.run_test() as pilot:
        await pilot.press("enter", "slash", *"2026-01-02")
        titles = column(app, TITLE_COLUMN)

    assert titles == ["Mid medium"]


async def test_the_active_session_is_marked(codex_tree: CodexTree) -> None:
    lines = [user_message("hello")]
    path = codex_tree.add_session(CODEX_SESSION, cwd=CWD, created=CODEX_CREATED, lines=lines)
    os.utime(path, (MODIFIED_AT.timestamp(), MODIFIED_AT.timestamp()))
    provider = CodexProvider(root=codex_tree.root, now=lambda: MODIFIED_AT + timedelta(minutes=1))
    app = AgentDeskApp(CatalogService([provider]))

    async with app.run_test() as pilot:
        await pilot.press("enter")
        states = column(app, STATE_COLUMN)

    assert states == ["active"]


async def test_inactive_sessions_are_not_marked(claude_tree: ClaudeTree) -> None:
    add_three_sessions(claude_tree)
    app = make_app(claude_tree)

    async with app.run_test() as pilot:
        await pilot.press("enter")
        states = column(app, STATE_COLUMN)

    assert states == ["", "", ""]


async def test_unreadable_lines_are_reported(claude_tree: ClaudeTree) -> None:
    project_dir = claude_tree.add_project(CWD)
    lines = [user_line("hi", cwd=CWD), CORRUPTED_LINE]
    claude_tree.add_session(project_dir, SESSION_OLD, lines)
    app = make_app(claude_tree)

    async with app.run_test() as pilot:
        await pilot.press("enter")
        note = str(app.screen.query_one("#note", Static).render())

    assert note == "Note: 1 unreadable lines were skipped."


async def test_escape_goes_back_to_the_projects(claude_tree: ClaudeTree) -> None:
    add_three_sessions(claude_tree)
    app = make_app(claude_tree)

    async with app.run_test() as pilot:
        await pilot.press("enter")
        opened = app.screen
        await pilot.press("escape")
        back = app.screen

    assert (type(opened), type(back)) == (SessionsScreen, ProjectsScreen)


async def test_escape_in_the_filter_returns_to_the_list_first(claude_tree: ClaudeTree) -> None:
    add_three_sessions(claude_tree)
    app = make_app(claude_tree)

    async with app.run_test() as pilot:
        await pilot.press("enter", "slash", "escape")
        screen = app.screen
        focused = app.focused

    assert type(screen) is SessionsScreen
    assert isinstance(focused, DataTable)
