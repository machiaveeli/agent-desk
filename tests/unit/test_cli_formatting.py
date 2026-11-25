from datetime import UTC, datetime
from pathlib import Path

import pytest

from agent_desk.cli.formatting import (
    format_projects_table,
    format_sessions_table,
    format_table,
    format_trash_table,
)
from agent_desk.display import format_trash_status
from agent_desk.domain.models import (
    Project,
    Session,
    SessionSummary,
    TrashEntry,
    TrashEntryState,
    TrashItem,
)
from agent_desk.services.catalog import ProjectOverview
from agent_desk.services.trash import ListedEntry

SESSION_ID = "00000000-0000-4000-8000-000000000001"


def test_table_aligns_columns_to_the_widest_cell() -> None:
    table = format_table(["NAME", "SIZE"], [["a", "10 B"], ["longer", "2 B"]])

    assert table.splitlines() == [
        "NAME    SIZE",
        "a       10 B",
        "longer  2 B",
    ]


def test_projects_table_row_shows_each_total() -> None:
    project = Project("claude-code", Path("/data/-work-app"), Path("/work/app"))
    overview = ProjectOverview(project, 3, datetime(2026, 1, 1, 10, 5, tzinfo=UTC), 1500)

    _, row = format_projects_table([overview], UTC).splitlines()

    assert row.split() == [
        "claude-code",
        str(Path("/work/app")),
        "3",
        "2026-01-01",
        "10:05",
        "1.5",
        "kB",
    ]


def test_sessions_table_row_shows_dates_size_and_a_one_line_title() -> None:
    session = Session("claude-code", SESSION_ID, Path("/data/s.jsonl"), None, Path("/work/app"))
    summary = SessionSummary(
        session=session,
        title="two\nlines",
        started_at=datetime(2026, 1, 1, 10, 5, tzinfo=UTC),
        ended_at=datetime(2026, 1, 1, 11, 30, tzinfo=UTC),
        first_prompt=None,
        size_bytes=42,
        invalid_line_count=0,
    )

    _, row = format_sessions_table([summary], UTC).splitlines()

    assert row.endswith(f"{SESSION_ID}  2026-01-01 10:05  2026-01-01 11:30  42 B  two lines")


def make_trash_entry(*, state: TrashEntryState = "complete", cwd: Path | None) -> TrashEntry:
    item = TrashItem(Path("/data/s.jsonl").absolute(), "s.jsonl", "file", 1500)
    return TrashEntry(
        entry_id="20261123T140512Z-3f2a9c1e",
        state=state,
        provider_id="claude-code",
        session_id="3f2a9c1e",
        cwd=cwd,
        title="two\nlines",
        trashed_at=datetime(2026, 11, 23, 14, 5, 12, tzinfo=UTC),
        items=(item,),
    )


def test_trash_table_row_shows_id_date_size_status_project_and_title() -> None:
    entry = make_trash_entry(cwd=Path("/work/app"))

    _, row = format_trash_table([ListedEntry(entry, is_expired=True)], UTC).splitlines()

    assert row.split() == [
        "20261123T140512Z-3f2a9c1e",
        "2026-11-23",
        "14:05",
        "1.5",
        "kB",
        "expired",
        "claude-code",
        str(Path("/work/app")),
        "two",
        "lines",
    ]


@pytest.mark.parametrize(
    ("state", "is_expired", "status"),
    [
        ("complete", False, "-"),
        ("complete", True, "expired"),
        ("pending", False, "incomplete"),
        ("pending", True, "incomplete"),
    ],
)
def test_trash_status_says_incomplete_before_expired(
    state: TrashEntryState, is_expired: bool, status: str
) -> None:
    entry = make_trash_entry(state=state, cwd=None)

    assert format_trash_status(ListedEntry(entry, is_expired)) == status


def test_trash_table_shows_a_dash_for_an_unknown_project() -> None:
    entry = make_trash_entry(cwd=None)

    _, row = format_trash_table([ListedEntry(entry, is_expired=False)], UTC).splitlines()

    assert row.split()[6:8] == ["claude-code", "-"]
