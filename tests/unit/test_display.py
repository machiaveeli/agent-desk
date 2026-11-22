from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path

import pytest

from agent_desk.display import (
    TITLE_MAX_LENGTH,
    format_moment,
    format_project_label,
    format_size,
    format_title,
)
from agent_desk.domain.models import Project


@pytest.mark.parametrize(
    ("size_bytes", "expected"),
    [
        (0, "0 B"),
        (999, "999 B"),
        (1000, "1.0 kB"),
        (1500, "1.5 kB"),
        (999_949, "999.9 kB"),
        (999_950, "1.0 MB"),
        (1_000_000, "1.0 MB"),
        (2_500_000_000, "2.5 GB"),
        (3_000_000_000_000, "3000.0 GB"),
    ],
)
def test_size_uses_decimal_units(size_bytes: int, expected: str) -> None:
    assert format_size(size_bytes) == expected


def test_moment_is_shown_in_the_given_timezone_to_the_minute() -> None:
    moment = datetime(2026, 1, 1, 10, 5, 59, tzinfo=UTC)
    brasilia = timezone(timedelta(hours=-3))

    assert format_moment(moment, brasilia) == "2026-01-01 07:05"


def test_missing_moment_is_a_dash() -> None:
    assert format_moment(None, UTC) == "-"


def test_project_label_is_its_cwd_or_its_folder_when_unknown() -> None:
    known = Project("claude-code", Path("/data/-work-app"), Path("/work/app"))
    unknown = Project("claude-code", Path("/data/-work-app"), None)

    assert (format_project_label(known), format_project_label(unknown)) == (
        str(Path("/work/app")),
        "(unknown cwd) -work-app",
    )


@pytest.mark.parametrize(
    ("title", "expected"),
    [
        ("x" * TITLE_MAX_LENGTH, "x" * TITLE_MAX_LENGTH),
        ("x" * (TITLE_MAX_LENGTH + 1), "x" * (TITLE_MAX_LENGTH - 1) + "…"),
        ("two\nlines", "two lines"),
    ],
    ids=["at-the-limit-is-kept", "over-the-limit-is-truncated", "fits-on-one-line"],
)
def test_title_fits_one_table_cell(title: str, expected: str) -> None:
    assert format_title(title) == expected
