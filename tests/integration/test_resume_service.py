from pathlib import Path

import pytest

from agent_desk.domain.errors import ResumeError
from agent_desk.providers.claude_code import ClaudeCodeProvider
from agent_desk.providers.processes import NOT_RUNNING, ProcessState
from agent_desk.services.catalog import CatalogService
from agent_desk.services.resume import ResumePlan, ResumeService
from fixtures.claude_tree import FAKE_PROC_START, ClaudeTree, custom_title_line, user_line

SESSION_ID = "00000000-0000-4000-8000-000000000001"
CLAUDE_PATH = "/fake/bin/claude"
PID = 4242
EXIT_CODE = 7


class RecordingLauncher:
    def __init__(self) -> None:
        self.calls: list[tuple[list[str], Path]] = []

    def __call__(self, argv: list[str], cwd: Path) -> int:
        self.calls.append((argv, cwd))
        return EXIT_CODE


@pytest.fixture
def cwd(tmp_path: Path) -> Path:
    path = tmp_path / "work" / "app"
    path.mkdir(parents=True)
    return path


def make_service(
    claude_tree: ClaudeTree,
    *,
    launcher: RecordingLauncher | None = None,
    executables: dict[str, str] | None = None,
    running: ProcessState = NOT_RUNNING,
) -> ResumeService:
    found = {"claude": CLAUDE_PATH} if executables is None else executables
    provider = ClaudeCodeProvider(
        root=claude_tree.root, inspect_process=lambda pid: running if pid == PID else NOT_RUNNING
    )
    return ResumeService(
        catalog=CatalogService([provider]),
        find_executable=found.get,
        launch=launcher or RecordingLauncher(),
    )


def add_session(claude_tree: ClaudeTree, cwd: Path) -> None:
    project_dir = claude_tree.add_project(str(cwd))
    claude_tree.add_session(project_dir, SESSION_ID, [user_line("hi", cwd=str(cwd))])


def test_plan_runs_the_provider_cli_found_on_path_inside_the_session_cwd(
    claude_tree: ClaudeTree, cwd: Path
) -> None:
    add_session(claude_tree, cwd)

    plan = make_service(claude_tree).prepare(SESSION_ID)

    assert plan == ResumePlan(argv=[CLAUDE_PATH, "--resume", SESSION_ID], cwd=cwd, is_active=False)


def test_launch_hands_argv_and_cwd_to_the_launcher_and_returns_its_exit_code(
    claude_tree: ClaudeTree, cwd: Path
) -> None:
    add_session(claude_tree, cwd)
    launcher = RecordingLauncher()
    service = make_service(claude_tree, launcher=launcher)
    plan = service.prepare(SESSION_ID)
    assert isinstance(plan, ResumePlan)

    exit_code = service.launch_plan(plan)

    assert (exit_code, launcher.calls) == (
        EXIT_CODE,
        [([CLAUDE_PATH, "--resume", SESSION_ID], cwd)],
    )


def test_plan_of_an_active_session_says_so(claude_tree: ClaudeTree, cwd: Path) -> None:
    add_session(claude_tree, cwd)
    claude_tree.add_active_session_file(pid=PID, session_id=SESSION_ID, cwd=str(cwd))
    running = ProcessState(is_running=True, start_marker=FAKE_PROC_START)

    plan = make_service(claude_tree, running=running).prepare(SESSION_ID)

    assert isinstance(plan, ResumePlan)
    assert plan.is_active is True


def test_unknown_session_id_is_refused(claude_tree: ClaudeTree, cwd: Path) -> None:
    add_session(claude_tree, cwd)

    result = make_service(claude_tree).prepare("no-such-session")

    assert isinstance(result, ResumeError)
    assert result.reason == "session_not_found"


def test_session_whose_cwd_no_longer_exists_is_refused(claude_tree: ClaudeTree, cwd: Path) -> None:
    add_session(claude_tree, cwd)
    cwd.rmdir()

    result = make_service(claude_tree).prepare(SESSION_ID)

    assert isinstance(result, ResumeError)
    assert result.reason == "cwd_missing"


def test_session_without_a_recorded_cwd_is_refused(claude_tree: ClaudeTree) -> None:
    project_dir = claude_tree.add_project("/work/app")
    claude_tree.add_session(project_dir, SESSION_ID, [custom_title_line("no cwd here")])

    result = make_service(claude_tree).prepare(SESSION_ID)

    assert isinstance(result, ResumeError)
    assert result.reason == "cwd_unknown"


def test_provider_cli_missing_from_path_is_refused(claude_tree: ClaudeTree, cwd: Path) -> None:
    add_session(claude_tree, cwd)

    result = make_service(claude_tree, executables={}).prepare(SESSION_ID)

    assert isinstance(result, ResumeError)
    assert result.reason == "cli_not_found"


def test_nothing_is_launched_while_preparing(claude_tree: ClaudeTree, cwd: Path) -> None:
    add_session(claude_tree, cwd)
    launcher = RecordingLauncher()

    make_service(claude_tree, launcher=launcher).prepare(SESSION_ID)

    assert launcher.calls == []
