"""Pilot tests for the projects screen. The catalog reads synthetic trees in tmp_path."""

from datetime import datetime

from textual.widgets import DataTable, HelpPanel, Input, Static

from agent_desk.providers.claude_code import ClaudeCodeProvider
from agent_desk.providers.codex import CodexProvider
from agent_desk.services.catalog import CatalogService
from agent_desk.tui.app import AgentDeskApp
from fixtures.claude_tree import ClaudeTree, user_line
from fixtures.codex_tree import CodexTree, user_message

CLAUDE_SESSION = "00000000-0000-4000-8000-00000000000a"
CLAUDE_SESSION_2 = "00000000-0000-4000-8000-00000000000b"
CODEX_SESSION = "00000000-0000-4000-8000-0000000000c1"
CLAUDE_CWD = "/work/web"
CODEX_CWD = "/work/api"
CODEX_CREATED = datetime(2026, 1, 1, 10, 0, 0)


def make_app(claude_tree: ClaudeTree, codex_tree: CodexTree) -> AgentDeskApp:
    catalog = CatalogService(
        [ClaudeCodeProvider(root=claude_tree.root), CodexProvider(root=codex_tree.root)]
    )
    return AgentDeskApp(catalog)


def add_claude_project(claude_tree: ClaudeTree) -> None:
    project_dir = claude_tree.add_project(CLAUDE_CWD)
    claude_tree.add_session(project_dir, CLAUDE_SESSION, [user_line("hi", cwd=CLAUDE_CWD)])
    claude_tree.add_session(project_dir, CLAUDE_SESSION_2, [user_line("yo", cwd=CLAUDE_CWD)])


def add_codex_project(codex_tree: CodexTree) -> None:
    lines = [user_message("hello", minute=1)]
    codex_tree.add_session(CODEX_SESSION, cwd=CODEX_CWD, created=CODEX_CREATED, lines=lines)


def table_rows(app: AgentDeskApp) -> list[tuple[str, str, str]]:
    """Provider, project and session count of each row, in display order."""
    table = app.screen.query_one(DataTable)
    rows = [table.get_row_at(index) for index in range(table.row_count)]
    return [(str(row[0]), str(row[1]), str(row[2])) for row in rows]


async def test_projects_of_both_providers_are_listed_together(
    claude_tree: ClaudeTree, codex_tree: CodexTree
) -> None:
    add_claude_project(claude_tree)
    add_codex_project(codex_tree)
    app = make_app(claude_tree, codex_tree)

    async with app.run_test():
        rows = table_rows(app)

    assert sorted(rows) == [("claude-code", CLAUDE_CWD, "2"), ("codex", CODEX_CWD, "1")]


async def test_typing_in_the_filter_keeps_only_matching_projects(
    claude_tree: ClaudeTree, codex_tree: CodexTree
) -> None:
    add_claude_project(claude_tree)
    add_codex_project(codex_tree)
    app = make_app(claude_tree, codex_tree)

    async with app.run_test() as pilot:
        await pilot.press("/", *"API")
        rows = table_rows(app)

    assert rows == [("codex", CODEX_CWD, "1")]


async def test_a_missing_provider_shows_a_friendly_note(
    claude_tree: ClaudeTree, codex_tree: CodexTree
) -> None:
    add_claude_project(claude_tree)
    app = make_app(claude_tree, codex_tree)

    async with app.run_test():
        note = str(app.screen.query_one("#note", Static).render())

    assert note == f"Note: no codex data found at {codex_tree.root}."


async def test_no_projects_at_all_says_so(claude_tree: ClaudeTree, codex_tree: CodexTree) -> None:
    (claude_tree.root / "projects").mkdir(parents=True)
    codex_tree.root.mkdir(parents=True)
    app = make_app(claude_tree, codex_tree)

    async with app.run_test():
        note = str(app.screen.query_one("#note", Static).render())

    assert note == "No projects found."


async def test_question_mark_toggles_the_help_panel(
    claude_tree: ClaudeTree, codex_tree: CodexTree
) -> None:
    add_claude_project(claude_tree)
    app = make_app(claude_tree, codex_tree)

    async with app.run_test() as pilot:
        await pilot.press("question_mark")
        shown = len(app.screen.query(HelpPanel))
        await pilot.press("question_mark")
        hidden = len(app.screen.query(HelpPanel))

    assert (shown, hidden) == (1, 0)


async def test_q_quits_the_app(claude_tree: ClaudeTree, codex_tree: CodexTree) -> None:
    add_claude_project(claude_tree)
    app = make_app(claude_tree, codex_tree)

    async with app.run_test() as pilot:
        await pilot.press("q")
        is_running = app.is_running

    assert not is_running


async def test_q_typed_in_the_filter_is_text_not_quit(
    claude_tree: ClaudeTree, codex_tree: CodexTree
) -> None:
    add_claude_project(claude_tree)
    app = make_app(claude_tree, codex_tree)

    async with app.run_test() as pilot:
        await pilot.press("/", "q")
        typed = app.screen.query_one(Input).value

    assert typed == "q"
