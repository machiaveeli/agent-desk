from datetime import UTC, datetime
from pathlib import Path

import pytest

from agent_desk.domain.models import Session, SessionSummary

PROVIDER_ID = "fake-provider"
SESSION_ID = "00000000-0000-4000-8000-000000000001"
EARLIER = datetime(2026, 1, 1, 10, 0, tzinfo=UTC)
LATER = datetime(2026, 1, 1, 11, 0, tzinfo=UTC)


def make_session(sibling_dir: Path | None = None) -> Session:
    return Session(
        provider_id=PROVIDER_ID,
        session_id=SESSION_ID,
        path=Path("/data/project") / f"{SESSION_ID}.jsonl",
        sibling_dir=sibling_dir,
        cwd=Path("/work/project"),
    )


def make_summary(**changes: object) -> SessionSummary:
    fields: dict[str, object] = {
        "session": make_session(),
        "title": "A title",
        "started_at": EARLIER,
        "ended_at": LATER,
        "user_message_count": 1,
        "assistant_message_count": 1,
        "first_prompt": "hello",
        "size_bytes": 10,
        "invalid_line_count": 0,
    }
    fields.update(changes)
    return SessionSummary(**fields)  # type: ignore[arg-type]


def test_session_files_include_the_sibling_dir_when_it_exists() -> None:
    sibling_dir = Path("/data/project") / SESSION_ID
    session = make_session(sibling_dir=sibling_dir)

    assert session.files() == (session.path, sibling_dir)


def test_session_files_are_only_the_transcript_without_a_sibling_dir() -> None:
    session = make_session(sibling_dir=None)

    assert session.files() == (session.path,)


def test_summary_accepts_a_session_without_timestamps() -> None:
    summary = make_summary(started_at=None, ended_at=None)

    assert summary.started_at is None


@pytest.mark.parametrize(
    "changes",
    [
        {"started_at": LATER, "ended_at": EARLIER},
        {"started_at": EARLIER, "ended_at": None},
        {"started_at": None, "ended_at": LATER},
        {"started_at": datetime(2026, 1, 1, 10, 0), "ended_at": datetime(2026, 1, 1, 11, 0)},
        {"user_message_count": -1},
        {"assistant_message_count": -1},
        {"size_bytes": -1},
        {"invalid_line_count": -1},
    ],
    ids=[
        "ends-before-start",
        "start-without-end",
        "end-without-start",
        "naive-datetimes",
        "negative-user-count",
        "negative-assistant-count",
        "negative-size",
        "negative-invalid-lines",
    ],
)
def test_summary_rejects_impossible_values(changes: dict[str, object]) -> None:
    with pytest.raises(ValueError):
        make_summary(**changes)
