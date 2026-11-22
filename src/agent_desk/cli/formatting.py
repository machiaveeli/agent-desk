"""Turns catalog results into plain-text tables for the terminal."""

from collections.abc import Sequence
from datetime import tzinfo

from agent_desk.display import format_moment, format_project_label, format_size, format_title
from agent_desk.domain.models import SessionSummary
from agent_desk.services.catalog import ProjectOverview

COLUMN_GAP = "  "


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
