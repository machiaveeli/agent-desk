from pathlib import Path

from agent_desk.domain.models import Project
from agent_desk.providers.claude_code import ClaudeCodeProvider
from fixtures.claude_tree import ClaudeTree, custom_title_line, user_line

PROVIDER_ID = "claude-code"
FIRST_SESSION = "00000000-0000-4000-8000-000000000001"
SECOND_SESSION = "00000000-0000-4000-8000-000000000002"
THIRD_SESSION = "00000000-0000-4000-8000-000000000003"
SHARED_FOLDER_CWD = "/work/my-app"
COLLIDING_CWD = "/work/my/app"


def make_provider(claude_tree: ClaudeTree) -> ClaudeCodeProvider:
    return ClaudeCodeProvider(root=claude_tree.root)


def list_session_ids(claude_tree: ClaudeTree, project: Project) -> list[str]:
    summaries = make_provider(claude_tree).list_sessions(project)
    return [summary.session.session_id for summary in summaries]


def test_only_sessions_of_the_project_cwd_are_listed(claude_tree: ClaudeTree) -> None:
    project_dir = claude_tree.add_project(SHARED_FOLDER_CWD)
    claude_tree.add_session(project_dir, FIRST_SESSION, [user_line("a", cwd=SHARED_FOLDER_CWD)])
    claude_tree.add_session(project_dir, SECOND_SESSION, [user_line("b", cwd=COLLIDING_CWD)])
    project = Project(PROVIDER_ID, project_dir, Path(COLLIDING_CWD))

    assert list_session_ids(claude_tree, project) == [SECOND_SESSION]


def test_session_without_cwd_joins_the_only_project_of_its_folder(
    claude_tree: ClaudeTree,
) -> None:
    project_dir = claude_tree.add_project(SHARED_FOLDER_CWD)
    claude_tree.add_session(project_dir, FIRST_SESSION, [user_line("a", cwd=SHARED_FOLDER_CWD)])
    claude_tree.add_session(project_dir, SECOND_SESSION, [custom_title_line("no cwd")])
    project = Project(PROVIDER_ID, project_dir, Path(SHARED_FOLDER_CWD))

    assert list_session_ids(claude_tree, project) == [FIRST_SESSION, SECOND_SESSION]


def test_session_without_cwd_in_a_shared_folder_goes_to_an_unknown_project(
    claude_tree: ClaudeTree,
) -> None:
    project_dir = claude_tree.add_project(SHARED_FOLDER_CWD)
    claude_tree.add_session(project_dir, FIRST_SESSION, [user_line("a", cwd=SHARED_FOLDER_CWD)])
    claude_tree.add_session(project_dir, SECOND_SESSION, [user_line("b", cwd=COLLIDING_CWD)])
    claude_tree.add_session(project_dir, THIRD_SESSION, [custom_title_line("no cwd")])

    projects = make_provider(claude_tree).discover_projects()

    assert projects == [
        Project(PROVIDER_ID, project_dir, Path(SHARED_FOLDER_CWD)),
        Project(PROVIDER_ID, project_dir, Path(COLLIDING_CWD)),
        Project(PROVIDER_ID, project_dir, None),
    ]
    assert list_session_ids(claude_tree, projects[2]) == [THIRD_SESSION]


def test_sessions_are_listed_most_recent_first_and_undated_last(
    claude_tree: ClaudeTree,
) -> None:
    project_dir = claude_tree.add_project(SHARED_FOLDER_CWD)
    claude_tree.add_session(project_dir, FIRST_SESSION, [custom_title_line("undated")])
    claude_tree.add_session(
        project_dir, SECOND_SESSION, [user_line("old", cwd=SHARED_FOLDER_CWD, minute=1)]
    )
    claude_tree.add_session(
        project_dir, THIRD_SESSION, [user_line("new", cwd=SHARED_FOLDER_CWD, minute=9)]
    )
    project = Project(PROVIDER_ID, project_dir, Path(SHARED_FOLDER_CWD))

    assert list_session_ids(claude_tree, project) == [THIRD_SESSION, SECOND_SESSION, FIRST_SESSION]


def test_jsonl_files_inside_sibling_dirs_are_not_sessions(claude_tree: ClaudeTree) -> None:
    project_dir = claude_tree.add_project(SHARED_FOLDER_CWD)
    claude_tree.add_session(project_dir, FIRST_SESSION, [user_line("a", cwd=SHARED_FOLDER_CWD)])
    claude_tree.add_sibling_file(project_dir, FIRST_SESSION, "subagents/agent-1.jsonl", "{}\n")
    project = Project(PROVIDER_ID, project_dir, Path(SHARED_FOLDER_CWD))

    assert list_session_ids(claude_tree, project) == [FIRST_SESSION]


def test_folder_without_sessions_lists_nothing(claude_tree: ClaudeTree) -> None:
    project_dir = claude_tree.add_project(SHARED_FOLDER_CWD)

    assert list_session_ids(claude_tree, Project(PROVIDER_ID, project_dir, None)) == []


def test_sessions_with_the_same_end_date_are_listed_by_id(claude_tree: ClaudeTree) -> None:
    project_dir = claude_tree.add_project(SHARED_FOLDER_CWD)
    claude_tree.add_session(project_dir, SECOND_SESSION, [user_line("b", cwd=SHARED_FOLDER_CWD)])
    claude_tree.add_session(project_dir, FIRST_SESSION, [user_line("a", cwd=SHARED_FOLDER_CWD)])
    project = Project(PROVIDER_ID, project_dir, Path(SHARED_FOLDER_CWD))

    assert list_session_ids(claude_tree, project) == [FIRST_SESSION, SECOND_SESSION]
