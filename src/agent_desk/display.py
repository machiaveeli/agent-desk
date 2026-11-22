"""Turns domain values into short display text, shared by the CLI tables and the TUI."""

from datetime import datetime, tzinfo

from agent_desk.domain.models import Project
from agent_desk.domain.text import truncate

TITLE_MAX_LENGTH = 60
MOMENT_FORMAT = "%Y-%m-%d %H:%M"
NO_VALUE = "-"
BYTES_PER_UNIT = 1000
SIZE_UNITS = ("kB", "MB", "GB")


def format_project_label(project: Project) -> str:
    if project.cwd is not None:
        return str(project.cwd)
    return f"(unknown cwd) {project.storage_dir.name}"


def format_title(title: str) -> str:
    return truncate(" ".join(title.split()), TITLE_MAX_LENGTH)


def format_moment(moment: datetime | None, tz: tzinfo | None) -> str:
    """`tz` None means the machine's local timezone."""
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
