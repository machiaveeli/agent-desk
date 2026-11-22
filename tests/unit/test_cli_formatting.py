from datetime import UTC, datetime
from pathlib import Path

from agent_desk.cli.formatting import format_projects_table, format_sessions_table, format_table
from agent_desk.domain.models import Project, Session, SessionSummary
from agent_desk.services.catalog import ProjectOverview

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
