import os
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from agent_desk.domain.models import Session
from agent_desk.providers.codex import CodexProvider
from fixtures.codex_tree import CodexTree, user_message

PROVIDER_ID = "codex"
SESSION_ID = "00000000-0000-4000-8000-0000000000c1"
CWD = "/work/app"
CREATED = datetime(2026, 1, 1, 10, 0, 0)
THRESHOLD_MINUTES = 10
MODIFIED_AT = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)


def make_session(codex_tree: CodexTree) -> Session:
    path = codex_tree.add_session(SESSION_ID, cwd=CWD, created=CREATED, lines=[user_message("hi")])
    os.utime(path, (MODIFIED_AT.timestamp(), MODIFIED_AT.timestamp()))
    return Session(PROVIDER_ID, SESSION_ID, path, None, Path(CWD))


def is_active_at(
    codex_tree: CodexTree,
    session: Session,
    moment: datetime,
    threshold_minutes: int = THRESHOLD_MINUTES,
) -> bool:
    provider = CodexProvider(
        root=codex_tree.root, active_threshold_minutes=threshold_minutes, now=lambda: moment
    )
    return provider.is_active(session)


@pytest.mark.parametrize(
    ("elapsed", "expected"),
    [
        (timedelta(minutes=9, seconds=59), True),
        (timedelta(minutes=10), False),
        (timedelta(minutes=10, seconds=1), False),
    ],
    ids=["9m59s", "10m", "10m01s"],
)
def test_session_is_active_while_modified_less_than_the_threshold_ago(
    codex_tree: CodexTree, elapsed: timedelta, expected: bool
) -> None:
    session = make_session(codex_tree)

    assert is_active_at(codex_tree, session, MODIFIED_AT + elapsed) is expected


def test_session_whose_rollout_is_gone_is_not_active(codex_tree: CodexTree) -> None:
    session = make_session(codex_tree)
    session.path.unlink()

    assert is_active_at(codex_tree, session, MODIFIED_AT) is False


def test_threshold_comes_from_the_config(codex_tree: CodexTree) -> None:
    session = make_session(codex_tree)

    moment = MODIFIED_AT + timedelta(minutes=20)
    assert is_active_at(codex_tree, session, moment, threshold_minutes=30) is True
