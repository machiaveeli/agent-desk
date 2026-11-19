import os
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from agent_desk.domain.models import Session
from agent_desk.providers.codex import CodexProvider
from agent_desk.services.catalog import CatalogService
from agent_desk.services.resume import ResumePlan, ResumeService
from fixtures.codex_tree import CodexTree, user_message

SESSION_ID = "00000000-0000-4000-8000-0000000000c1"
CODEX_PATH = "/fake/bin/codex"
CREATED = datetime(2026, 1, 1, 10, 0, 0)
MODIFIED_AT = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
LONG_AFTER = MODIFIED_AT + timedelta(hours=1)


@pytest.fixture
def cwd(tmp_path: Path) -> Path:
    path = tmp_path / "work" / "app"
    path.mkdir(parents=True)
    return path


def never_launch(argv: list[str], cwd: Path) -> int:
    raise AssertionError("prepare() must not start a process")


def make_service(codex_tree: CodexTree, now: datetime) -> ResumeService:
    provider = CodexProvider(root=codex_tree.root, now=lambda: now)
    return ResumeService(
        catalog=CatalogService([provider]),
        find_executable={"codex": CODEX_PATH}.get,
        launch=never_launch,
    )


def add_session(codex_tree: CodexTree, cwd: Path) -> Path:
    path = codex_tree.add_session(
        SESSION_ID, cwd=str(cwd), created=CREATED, lines=[user_message("hi")]
    )
    os.utime(path, (MODIFIED_AT.timestamp(), MODIFIED_AT.timestamp()))
    return path


def test_resume_command_is_codex_resume_with_the_session_id(codex_tree: CodexTree) -> None:
    session = Session("codex", SESSION_ID, Path("rollout.jsonl"), None, None)

    # `codex resume <SESSION_ID>` takes the session UUID (codex-rs/cli/src/main.rs).
    assert CodexProvider(root=codex_tree.root).resume_command(session) == [
        "codex",
        "resume",
        SESSION_ID,
    ]


def test_plan_runs_codex_found_on_path_inside_the_session_cwd(
    codex_tree: CodexTree, cwd: Path
) -> None:
    add_session(codex_tree, cwd)

    plan = make_service(codex_tree, LONG_AFTER).prepare(SESSION_ID)

    assert plan == ResumePlan(argv=[CODEX_PATH, "resume", SESSION_ID], cwd=cwd, is_active=False)


def test_plan_of_a_recently_written_rollout_is_marked_active(
    codex_tree: CodexTree, cwd: Path
) -> None:
    add_session(codex_tree, cwd)

    plan = make_service(codex_tree, MODIFIED_AT + timedelta(minutes=1)).prepare(SESSION_ID)

    assert isinstance(plan, ResumePlan)
    assert plan.is_active is True
