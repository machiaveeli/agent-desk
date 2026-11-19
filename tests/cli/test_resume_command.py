from pathlib import Path

import pytest
from typer.testing import CliRunner, Result

from agent_desk.cli.main import Dependencies, app
from agent_desk.providers.claude_code import ClaudeCodeProvider
from agent_desk.providers.processes import ProcessState
from agent_desk.services.catalog import CatalogService
from fixtures.claude_tree import FAKE_PROC_START, ClaudeTree, user_line

SESSION_ID = "00000000-0000-4000-8000-000000000001"
CLAUDE_PATH = "/fake/bin/claude"
PID = 4242
CHILD_EXIT_CODE = 7
EXIT_FAILURE = 1

runner = CliRunner()


@pytest.fixture
def cwd(tmp_path: Path, claude_tree: ClaudeTree) -> Path:
    """The project folder, holding one session in the synthetic tree."""
    path = tmp_path / "work" / "app"
    path.mkdir(parents=True)
    project_dir = claude_tree.add_project(str(path))
    claude_tree.add_session(project_dir, SESSION_ID, [user_line("hi", cwd=str(path))])
    return path


def run(
    claude_tree: ClaudeTree,
    args: list[str],
    *,
    launched: list[tuple[list[str], Path]],
    is_active: bool = False,
    user_input: str | None = None,
) -> Result:
    running = ProcessState(is_running=is_active, start_marker=FAKE_PROC_START)
    provider = ClaudeCodeProvider(root=claude_tree.root, inspect_process=lambda pid: running)

    def launch(argv: list[str], cwd: Path) -> int:
        launched.append((argv, cwd))
        return CHILD_EXIT_CODE

    dependencies = Dependencies(
        load_catalog=lambda: CatalogService([provider]),
        find_executable={"claude": CLAUDE_PATH}.get,
        launch=launch,
    )
    return runner.invoke(app, args, obj=dependencies, input=user_input)


def test_resume_runs_the_cli_and_passes_its_exit_code_through(
    claude_tree: ClaudeTree, cwd: Path
) -> None:
    launched: list[tuple[list[str], Path]] = []

    result = run(claude_tree, ["resume", SESSION_ID], launched=launched)

    assert result.exit_code == CHILD_EXIT_CODE
    assert launched == [([CLAUDE_PATH, "--resume", SESSION_ID], cwd)]


def test_resume_refusal_is_a_clear_error(claude_tree: ClaudeTree, cwd: Path) -> None:
    launched: list[tuple[list[str], Path]] = []

    result = run(claude_tree, ["resume", "no-such-session"], launched=launched)

    assert result.exit_code == EXIT_FAILURE
    assert isinstance(result.exception, SystemExit), "a clean exit, not a crash"
    assert result.stderr == "Error: no session with id no-such-session.\n"
    assert launched == []


def test_resume_of_an_active_session_asks_first_and_stops_on_no(
    claude_tree: ClaudeTree, cwd: Path
) -> None:
    claude_tree.add_active_session_file(pid=PID, session_id=SESSION_ID, cwd=str(cwd))
    launched: list[tuple[list[str], Path]] = []

    result = run(
        claude_tree, ["resume", SESSION_ID], launched=launched, is_active=True, user_input="n\n"
    )

    assert result.exit_code == EXIT_FAILURE
    assert "is open in another terminal" in result.stdout
    assert launched == []


def test_resume_of_an_active_session_goes_on_after_yes(claude_tree: ClaudeTree, cwd: Path) -> None:
    claude_tree.add_active_session_file(pid=PID, session_id=SESSION_ID, cwd=str(cwd))
    launched: list[tuple[list[str], Path]] = []

    result = run(
        claude_tree, ["resume", SESSION_ID], launched=launched, is_active=True, user_input="y\n"
    )

    assert result.exit_code == CHILD_EXIT_CODE
    assert len(launched) == 1
