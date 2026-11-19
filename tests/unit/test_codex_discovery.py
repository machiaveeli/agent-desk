from datetime import datetime
from pathlib import Path

from agent_desk.domain.errors import ProviderNotFound
from agent_desk.domain.models import Project
from agent_desk.providers.codex import CodexProvider
from fixtures.codex_tree import CORRUPTED_LINE, CodexTree, session_meta, user_message

PROVIDER_ID = "codex"
FIRST_SESSION = "00000000-0000-4000-8000-0000000000c1"
SECOND_SESSION = "00000000-0000-4000-8000-0000000000c2"
THIRD_SESSION = "00000000-0000-4000-8000-0000000000c3"
APP_CWD = "/work/app"
OTHER_CWD = "/work/other-app"
CREATED = datetime(2026, 1, 1, 10, 0, 0)
NEXT_DAY = datetime(2026, 1, 2, 9, 30, 0)


def discover(codex_tree: CodexTree) -> list[Project] | ProviderNotFound:
    return CodexProvider(root=codex_tree.root).discover_projects()


def sessions_dir(codex_tree: CodexTree) -> Path:
    return codex_tree.root / "sessions"


def test_missing_root_is_reported_as_provider_not_found(codex_tree: CodexTree) -> None:
    assert discover(codex_tree) == ProviderNotFound(PROVIDER_ID, codex_tree.root)


def test_root_without_sessions_folder_has_no_projects(codex_tree: CodexTree) -> None:
    codex_tree.root.mkdir(parents=True)

    assert discover(codex_tree) == []


def test_rollouts_are_grouped_by_the_cwd_of_their_session_meta(codex_tree: CodexTree) -> None:
    codex_tree.add_session(FIRST_SESSION, cwd=APP_CWD, created=CREATED, lines=[])
    codex_tree.add_session(SECOND_SESSION, cwd=OTHER_CWD, created=CREATED, lines=[])
    codex_tree.add_session(THIRD_SESSION, cwd=APP_CWD, created=NEXT_DAY, lines=[])

    # Every Codex rollout lives under sessions/, whatever its project.
    assert discover(codex_tree) == [
        Project(PROVIDER_ID, sessions_dir(codex_tree), Path(APP_CWD)),
        Project(PROVIDER_ID, sessions_dir(codex_tree), Path(OTHER_CWD)),
    ]


def test_rollout_without_session_meta_leaves_the_cwd_unknown_and_comes_last(
    codex_tree: CodexTree,
) -> None:
    codex_tree.add_session(SECOND_SESSION, cwd=OTHER_CWD, created=CREATED, lines=[])
    codex_tree.add_raw_rollout(
        Path("2026", "01", "01", f"rollout-2026-01-01T10-00-00-{FIRST_SESSION}.jsonl"),
        f"{CORRUPTED_LINE}\n",
    )

    assert discover(codex_tree) == [
        Project(PROVIDER_ID, sessions_dir(codex_tree), Path(OTHER_CWD)),
        Project(PROVIDER_ID, sessions_dir(codex_tree), None),
    ]


def test_only_the_first_session_meta_sets_the_cwd(codex_tree: CodexTree) -> None:
    # A fork copies its parent's history, session_meta included, after its own first line.
    codex_tree.add_session(
        FIRST_SESSION,
        cwd=APP_CWD,
        created=CREATED,
        lines=[
            session_meta(
                SECOND_SESSION, cwd=OTHER_CWD, history_mode="legacy", source="cli", minute=0
            )
        ],
    )

    assert discover(codex_tree) == [Project(PROVIDER_ID, sessions_dir(codex_tree), Path(APP_CWD))]


def test_subagent_and_internal_rollouts_are_not_projects(codex_tree: CodexTree) -> None:
    codex_tree.add_session(
        FIRST_SESSION, cwd=APP_CWD, created=CREATED, lines=[], source={"subagent": "review"}
    )
    codex_tree.add_session(
        SECOND_SESSION,
        cwd=OTHER_CWD,
        created=CREATED,
        lines=[],
        source={"internal": "memory_consolidation"},
    )

    assert discover(codex_tree) == []


def test_files_that_are_not_dated_rollouts_are_ignored(codex_tree: CodexTree) -> None:
    codex_tree.add_session(FIRST_SESSION, cwd=APP_CWD, created=CREATED, lines=[user_message("a")])
    codex_tree.add_raw_rollout(Path("2026", "01", "01", "notes.jsonl"), "{}\n")
    codex_tree.add_raw_rollout(Path(f"rollout-2026-01-01T10-00-00-{SECOND_SESSION}.jsonl"), "")
    # Compressed cold rollouts need zstd, which Python 3.12 lacks: not read in v1.
    codex_tree.add_raw_rollout(
        Path("2026", "01", "01", f"rollout-2026-01-01T10-00-00-{THIRD_SESSION}.jsonl.zst"), ""
    )

    assert discover(codex_tree) == [Project(PROVIDER_ID, sessions_dir(codex_tree), Path(APP_CWD))]
