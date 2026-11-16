from pathlib import Path

import pytest

from agent_desk.domain.errors import ProviderNotFound
from agent_desk.domain.models import Project
from agent_desk.providers.claude_code import ClaudeCodeProvider
from fixtures.claude_tree import (
    CORRUPTED_LINE,
    UNKNOWN_TYPE_LINE,
    ClaudeTree,
    custom_title_line,
    text_block,
    user_line,
)

PROVIDER_ID = "claude-code"
FIRST_SESSION = "00000000-0000-4000-8000-000000000001"
SECOND_SESSION = "00000000-0000-4000-8000-000000000002"


def make_provider(claude_tree: ClaudeTree) -> ClaudeCodeProvider:
    return ClaudeCodeProvider(root=claude_tree.root)


def add_session_in(claude_tree: ClaudeTree, project_dir: Path, session_id: str, cwd: str) -> None:
    claude_tree.add_session(project_dir, session_id, [user_line([text_block("hi")], cwd=cwd)])


def test_missing_root_is_reported_as_provider_not_found(claude_tree: ClaudeTree) -> None:
    result = make_provider(claude_tree).discover_projects()

    assert result == ProviderNotFound(PROVIDER_ID, claude_tree.root)


def test_root_without_projects_folder_has_no_projects(claude_tree: ClaudeTree) -> None:
    claude_tree.root.mkdir(parents=True)

    assert make_provider(claude_tree).discover_projects() == []


def test_cwd_comes_from_the_session_even_when_it_contains_dashes(
    claude_tree: ClaudeTree,
) -> None:
    cwd = "/work/my-app"
    project_dir = claude_tree.add_project(cwd)
    add_session_in(claude_tree, project_dir, FIRST_SESSION, cwd)

    result = make_provider(claude_tree).discover_projects()

    assert result == [Project(PROVIDER_ID, project_dir, Path(cwd))]


def test_cwd_is_read_from_the_first_line_that_has_it(claude_tree: ClaudeTree) -> None:
    cwd = "/work/app"
    project_dir = claude_tree.add_project(cwd)
    claude_tree.add_session(
        project_dir,
        FIRST_SESSION,
        [
            CORRUPTED_LINE,
            UNKNOWN_TYPE_LINE,
            custom_title_line("no cwd here"),
            user_line("hi", cwd=cwd),
        ],
    )

    result = make_provider(claude_tree).discover_projects()

    assert result == [Project(PROVIDER_ID, project_dir, Path(cwd))]


def test_folder_without_sessions_is_a_project_with_unknown_cwd(claude_tree: ClaudeTree) -> None:
    project_dir = claude_tree.add_project("/work/empty")

    result = make_provider(claude_tree).discover_projects()

    assert result == [Project(PROVIDER_ID, project_dir, None)]


def test_folder_with_only_memory_is_a_project_with_unknown_cwd(claude_tree: ClaudeTree) -> None:
    project_dir = claude_tree.add_project("/work/notes")
    claude_tree.add_memory(project_dir, "MEMORY.md", "- a memory\n")

    result = make_provider(claude_tree).discover_projects()

    assert result == [Project(PROVIDER_ID, project_dir, None)]


def test_session_without_any_cwd_line_leaves_the_cwd_unknown(claude_tree: ClaudeTree) -> None:
    project_dir = claude_tree.add_project("/work/app")
    claude_tree.add_session(project_dir, FIRST_SESSION, [custom_title_line("only a title")])

    result = make_provider(claude_tree).discover_projects()

    assert result == [Project(PROVIDER_ID, project_dir, None)]


def test_sessions_of_one_folder_with_the_same_cwd_make_one_project(
    claude_tree: ClaudeTree,
) -> None:
    cwd = "/work/app"
    project_dir = claude_tree.add_project(cwd)
    add_session_in(claude_tree, project_dir, FIRST_SESSION, cwd)
    add_session_in(claude_tree, project_dir, SECOND_SESSION, cwd)

    result = make_provider(claude_tree).discover_projects()

    assert result == [Project(PROVIDER_ID, project_dir, Path(cwd))]


def test_cwds_that_encode_to_the_same_folder_are_separate_projects(
    claude_tree: ClaudeTree,
) -> None:
    # "/work/my-app" and "/work/my/app" both become "-work-my-app" on disk.
    project_dir = claude_tree.add_project("/work/my-app")
    add_session_in(claude_tree, project_dir, FIRST_SESSION, "/work/my/app")
    add_session_in(claude_tree, project_dir, SECOND_SESSION, "/work/my-app")

    result = make_provider(claude_tree).discover_projects()

    assert result == [
        Project(PROVIDER_ID, project_dir, Path("/work/my-app")),
        Project(PROVIDER_ID, project_dir, Path("/work/my/app")),
    ]


def test_projects_are_sorted_by_folder_and_stray_files_are_ignored(
    claude_tree: ClaudeTree,
) -> None:
    second_dir = claude_tree.add_project("/work/zeta")
    first_dir = claude_tree.add_project("/work/alpha")
    (claude_tree.root / "projects" / "stray.txt").write_bytes(b"not a project")

    result = make_provider(claude_tree).discover_projects()

    assert result == [
        Project(PROVIDER_ID, first_dir, None),
        Project(PROVIDER_ID, second_dir, None),
    ]


@pytest.mark.parametrize(
    "odd_cwd", ["", 5, None, ["/work/app"]], ids=["empty", "number", "null", "list"]
)
def test_cwd_values_that_are_not_a_path_are_skipped(
    claude_tree: ClaudeTree, odd_cwd: object
) -> None:
    cwd = "/work/app"
    project_dir = claude_tree.add_project(cwd)
    claude_tree.add_session(
        project_dir, FIRST_SESSION, [{"type": "user", "cwd": odd_cwd}, user_line("hi", cwd=cwd)]
    )

    result = make_provider(claude_tree).discover_projects()

    assert result == [Project(PROVIDER_ID, project_dir, Path(cwd))]
