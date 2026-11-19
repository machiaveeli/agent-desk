from datetime import datetime
from pathlib import Path

from agent_desk.domain.models import Project
from agent_desk.providers.codex import CodexProvider
from fixtures.codex_tree import CORRUPTED_LINE, CodexTree, user_message

PROVIDER_ID = "codex"
FIRST_SESSION = "00000000-0000-4000-8000-0000000000c1"
SECOND_SESSION = "00000000-0000-4000-8000-0000000000c2"
THIRD_SESSION = "00000000-0000-4000-8000-0000000000c3"
APP_CWD = "/work/app"
OTHER_CWD = "/work/other-app"
CREATED = datetime(2026, 1, 1, 10, 0, 0)


def project_for(codex_tree: CodexTree, cwd: str | None) -> Project:
    return Project(PROVIDER_ID, codex_tree.root / "sessions", Path(cwd) if cwd else None)


def list_session_ids(codex_tree: CodexTree, project: Project) -> list[str]:
    summaries = CodexProvider(root=codex_tree.root).list_sessions(project)
    return [summary.session.session_id for summary in summaries]


def test_only_sessions_of_the_project_cwd_are_listed(codex_tree: CodexTree) -> None:
    codex_tree.add_session(FIRST_SESSION, cwd=APP_CWD, created=CREATED, lines=[])
    codex_tree.add_session(SECOND_SESSION, cwd=OTHER_CWD, created=CREATED, lines=[])

    assert list_session_ids(codex_tree, project_for(codex_tree, OTHER_CWD)) == [SECOND_SESSION]


def test_sessions_are_listed_most_recent_first(codex_tree: CodexTree) -> None:
    codex_tree.add_session(
        FIRST_SESSION, cwd=APP_CWD, created=CREATED, lines=[user_message("a", minute=1)]
    )
    codex_tree.add_session(
        SECOND_SESSION, cwd=APP_CWD, created=CREATED, lines=[user_message("b", minute=9)]
    )
    codex_tree.add_session(
        THIRD_SESSION, cwd=APP_CWD, created=CREATED, lines=[user_message("c", minute=5)]
    )

    assert list_session_ids(codex_tree, project_for(codex_tree, APP_CWD)) == [
        SECOND_SESSION,
        THIRD_SESSION,
        FIRST_SESSION,
    ]


def test_rollout_without_session_meta_is_listed_under_the_unknown_project(
    codex_tree: CodexTree,
) -> None:
    codex_tree.add_session(FIRST_SESSION, cwd=APP_CWD, created=CREATED, lines=[])
    codex_tree.add_raw_rollout(
        Path("2026", "01", "01", f"rollout-2026-01-01T10-00-00-{SECOND_SESSION}.jsonl"),
        f"{CORRUPTED_LINE}\n",
    )

    # Without a session_meta the id still comes from the file name (rollout-<time>-<id>).
    assert list_session_ids(codex_tree, project_for(codex_tree, None)) == [SECOND_SESSION]


def test_reverted_thread_file_name_keeps_only_the_thread_id(codex_tree: CodexTree) -> None:
    rollout_id = "00000000-0000-4000-8000-0000000000aa"
    codex_tree.add_raw_rollout(
        Path("2026", "01", "01", f"rollout-2026-01-01T10-00-00-{FIRST_SESSION}_{rollout_id}.jsonl"),
        f"{CORRUPTED_LINE}\n",
    )

    assert list_session_ids(codex_tree, project_for(codex_tree, None)) == [FIRST_SESSION]


def test_subagent_rollouts_are_not_listed(codex_tree: CodexTree) -> None:
    codex_tree.add_session(FIRST_SESSION, cwd=APP_CWD, created=CREATED, lines=[])
    codex_tree.add_session(
        SECOND_SESSION, cwd=APP_CWD, created=CREATED, lines=[], source={"subagent": "review"}
    )

    assert list_session_ids(codex_tree, project_for(codex_tree, APP_CWD)) == [FIRST_SESSION]
