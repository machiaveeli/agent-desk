"""Turns catalog results into plain-text tables for the terminal."""

from collections.abc import Sequence
from datetime import datetime, tzinfo

from agent_desk.domain.models import Project, SessionSummary
from agent_desk.domain.text import truncate
from agent_desk.services.catalog import ProjectOverview

TITLE_MAX_LENGTH = 60
COLUMN_GAP = "  "
MOMENT_FORMAT = "%Y-%m-%d %H:%M"
NO_VALUE = "-"
BYTES_PER_UNIT = 1000
SIZE_UNITS = ("kB", "MB", "GB")


def format_projects_table(overviews: Sequence[ProjectOverview], tz: tzinfo | None = None) -> str:
    """`tz` None means the machine's local timezone."""
    rows = [
        [
            overview.project.provider_id,
            format_project_label(overview.project),
            str(overview.session_count),
            format_moment(overview.last_activity, tz),
            format_size(overview.size_bytes),
        ]
        for overview in overviews
    ]
    return format_table(["PROVIDER", "PROJECT", "SESSIONS", "LAST ACTIVITY", "SIZE"], rows)


def format_sessions_table(summaries: Sequence[SessionSummary], tz: tzinfo | None = None) -> str:
    rows = [
        [
            summary.session.provider_id,
            summary.session.session_id,
            format_moment(summary.started_at, tz),
            format_moment(summary.ended_at, tz),
            format_size(summary.size_bytes),
            format_title(summary.title),
        ]
        for summary in summaries
    ]
    # The title goes last: it is the widest column and the only one of free text.
    return format_table(["PROVIDER", "ID", "STARTED", "ENDED", "SIZE", "TITLE"], rows)


def format_table(headers: Sequence[str], rows: Sequence[Sequence[str]]) -> str:
    widths = [max(len(cell) for cell in column) for column in zip(headers, *rows, strict=True)]
    lines = [
        COLUMN_GAP.join(cell.ljust(width) for cell, width in zip(row, widths, strict=True))
        for row in [headers, *rows]
    ]
    return "\n".join(line.rstrip() for line in lines)


def format_project_label(project: Project) -> str:
    if project.cwd is not None:
        return str(project.cwd)
    return f"(unknown cwd) {project.storage_dir.name}"


def format_title(title: str) -> str:
    return truncate(" ".join(title.split()), TITLE_MAX_LENGTH)


def format_moment(moment: datetime | None, tz: tzinfo | None) -> str:
    if moment is None:
        return NO_VALUE
    return moment.astimezone(tz).strftime(MOMENT_FORMAT)


def format_size(size_bytes: int) -> str:
    if size_bytes < BYTES_PER_UNIT:
        return f"{size_bytes} B"
    size = size_bytes / BYTES_PER_UNIT
    for unit in SIZE_UNITS[:-1]:
        # Compared after rounding, so 999.95 kB becomes "1.0 MB" and never "1000.0 kB".
        if round(size, 1) < BYTES_PER_UNIT:
            return f"{size:.1f} {unit}"
        size /= BYTES_PER_UNIT
    return f"{size:.1f} {SIZE_UNITS[-1]}"
