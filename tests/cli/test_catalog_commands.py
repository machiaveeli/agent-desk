"""The catalog is injected through Typer's `obj`, so no test reads the real home or config."""

from pathlib import Path

import pytest
from typer.testing import CliRunner, Result

from agent_desk.cli.main import CatalogLoader, app
from agent_desk.domain.errors import ConfigError
from agent_desk.providers.claude_code import ClaudeCodeProvider
from agent_desk.services.catalog import CatalogService
from fixtures.claude_tree import CORRUPTED_LINE, ClaudeTree, custom_title_line, user_line

SESSION_A = "00000000-0000-4000-8000-00000000000a"
SESSION_B = "00000000-0000-4000-8000-00000000000b"
EXIT_FAILURE = 1
EXIT_USAGE_ERROR = 2

runner = CliRunner()


@pytest.fixture
def cwd(tmp_path: Path) -> Path:
    """A real absolute path on every OS, so the CLI can turn a relative path into it."""
    path = tmp_path / "work" / "app"
    path.mkdir(parents=True)
    return path


def run(claude_tree: ClaudeTree, args: list[str]) -> Result:
    def load_catalog() -> CatalogService:
        return CatalogService([ClaudeCodeProvider(root=claude_tree.root)])

    return invoke(args, load_catalog)


def invoke(args: list[str], load_catalog: CatalogLoader) -> Result:
    return runner.invoke(app, args, obj=load_catalog)


def add_two_sessions(claude_tree: ClaudeTree, cwd: Path) -> None:
    project_dir = claude_tree.add_project(str(cwd))
    lines = [custom_title_line("Fix the login"), user_line("hi", cwd=str(cwd), minute=1)]
    claude_tree.add_session(project_dir, SESSION_A, lines)
    claude_tree.add_session(project_dir, SESSION_B, [user_line("Add a cache", cwd=str(cwd))])


def test_projects_lists_each_project_with_its_session_count(
    claude_tree: ClaudeTree, cwd: Path
) -> None:
    add_two_sessions(claude_tree, cwd)

    result = run(claude_tree, ["projects"])

    assert result.exit_code == 0
    header, row = result.stdout.splitlines()
    assert header.split() == ["PROVIDER", "PROJECT", "SESSIONS", "LAST", "ACTIVITY", "SIZE"]
    assert row.split()[:3] == ["claude-code", str(cwd), "2"]


def test_projects_with_a_missing_provider_shows_a_friendly_note(claude_tree: ClaudeTree) -> None:
    result = run(claude_tree, ["projects"])

    assert result.exit_code == 0
    assert result.stdout == "No projects found.\n"
    assert result.stderr == f"Note: no claude-code data found at {claude_tree.root}.\n"


def test_config_error_is_reported_without_a_traceback() -> None:
    def load_catalog() -> ConfigError:
        return ConfigError("trash.retention_days", "wrong_type", "'trash' must be a table")

    result = invoke(["projects"], load_catalog)

    assert result.exit_code == EXIT_FAILURE
    assert isinstance(result.exception, SystemExit), "a clean exit, not a crash"
    assert result.stderr == "Error: config: 'trash' must be a table\n"


def test_sessions_lists_the_project_sessions_with_their_ids_and_titles(
    claude_tree: ClaudeTree, cwd: Path
) -> None:
    add_two_sessions(claude_tree, cwd)

    result = run(claude_tree, ["sessions", "--project", str(cwd)])

    assert result.exit_code == 0
    header, *rows = result.stdout.splitlines()
    assert header.split()[:2] == ["PROVIDER", "ID"]
    assert [row.split()[1] for row in rows] == [SESSION_A, SESSION_B]
    assert "Fix the login" in rows[0]
    assert "Add a cache" in rows[1]
    assert result.stderr == ""


def test_sessions_accepts_a_path_relative_to_the_current_folder(
    claude_tree: ClaudeTree, cwd: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    add_two_sessions(claude_tree, cwd)
    monkeypatch.chdir(cwd)

    result = run(claude_tree, ["sessions", "--project", "."])

    assert result.exit_code == 0
    assert SESSION_A in result.stdout


def test_sessions_reports_unreadable_lines(claude_tree: ClaudeTree, cwd: Path) -> None:
    project_dir = claude_tree.add_project(str(cwd))
    lines = [user_line("hi", cwd=str(cwd)), CORRUPTED_LINE, CORRUPTED_LINE]
    claude_tree.add_session(project_dir, SESSION_A, lines)

    result = run(claude_tree, ["sessions", "--project", str(cwd)])

    assert result.exit_code == 0
    assert result.stderr == "Note: 2 unreadable lines were skipped.\n"


def test_sessions_of_an_unknown_project_fails_with_a_clear_message(
    claude_tree: ClaudeTree, cwd: Path
) -> None:
    claude_tree.add_project("/somewhere/else")

    result = run(claude_tree, ["sessions", "--project", str(cwd)])

    assert result.exit_code == EXIT_FAILURE
    assert isinstance(result.exception, SystemExit), "a clean exit, not a crash"
    assert result.stdout == ""
    assert result.stderr == f"Error: no project found for {cwd}.\n"


def test_sessions_without_a_project_is_a_usage_error(claude_tree: ClaudeTree) -> None:
    result = run(claude_tree, ["sessions"])

    assert result.exit_code == EXIT_USAGE_ERROR
