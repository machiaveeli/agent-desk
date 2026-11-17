from contextlib import closing
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from agent_desk.config import CLAUDE_PROVIDER_ID
from agent_desk.domain.errors import ProviderNotFound
from agent_desk.domain.models import Project, SessionSummary
from agent_desk.providers.claude_summary import read_cwd, summarize_session
from agent_desk.providers.jsonl import read_json_lines

PROJECTS_DIR_NAME = "projects"
SESSION_FILE_PATTERN = "*.jsonl"
UNDATED = datetime.min.replace(tzinfo=UTC)


@dataclass(frozen=True)
class ClaudeCodeProvider:
    """Reads the Claude Code folder (`~/.claude` by default). It never writes."""

    root: Path

    @property
    def provider_id(self) -> str:
        return CLAUDE_PROVIDER_ID

    def discover_projects(self) -> list[Project] | ProviderNotFound:
        if not self.root.is_dir():
            return ProviderNotFound(self.provider_id, self.root)
        projects_dir = self.root / PROJECTS_DIR_NAME
        if not projects_dir.is_dir():
            return []
        storage_dirs = sorted(
            (child for child in projects_dir.iterdir() if child.is_dir()),
            key=lambda storage_dir: storage_dir.name,
        )
        return [
            project for storage_dir in storage_dirs for project in self.read_projects(storage_dir)
        ]

    def read_projects(self, storage_dir: Path) -> list[Project]:
        """One project per owner cwd (see `assign_owner_cwds`). A folder without sessions is
        still listed with an unknown cwd, since it may hold memory."""
        session_cwds = [read_session_cwd(path) for path in list_session_files(storage_dir)]
        owner_cwds = set(assign_owner_cwds(session_cwds)) or {None}
        return [
            Project(self.provider_id, storage_dir, cwd)
            for cwd in sorted(owner_cwds, key=sort_key_for_cwd)
        ]

    def list_sessions(self, project: Project) -> list[SessionSummary]:
        """The project's sessions, most recent first; undated sessions come last."""
        summaries = [
            summarize_session(path, self.provider_id)
            for path in list_session_files(project.storage_dir)
        ]
        owner_cwds = assign_owner_cwds([summary.session.cwd for summary in summaries])
        owned = [
            summary
            for summary, owner_cwd in zip(summaries, owner_cwds, strict=True)
            if owner_cwd == project.cwd
        ]
        # Files come sorted by name (the session id), and Python's sort is stable, also with
        # reverse=True: sessions with the same end date keep the id order.
        return sorted(owned, key=lambda summary: summary.ended_at or UNDATED, reverse=True)


def list_session_files(storage_dir: Path) -> list[Path]:
    # Only the top level: sibling dirs hold their own .jsonl files (subagents), not sessions.
    return sorted(storage_dir.glob(SESSION_FILE_PATTERN))


def assign_owner_cwds(session_cwds: list[Path | None]) -> list[Path | None]:
    """Maps each session to the cwd of the project that shows it.

    The folder name is a lossy encoding, so two cwds can share a folder. A session that has no
    cwd of its own joins the folder's project when the folder has exactly one known cwd;
    otherwise it cannot be placed and stays under an unknown cwd (None).
    """
    known_cwds = {cwd for cwd in session_cwds if cwd is not None}
    fallback_cwd = next(iter(known_cwds)) if len(known_cwds) == 1 else None
    return [cwd if cwd is not None else fallback_cwd for cwd in session_cwds]


def sort_key_for_cwd(cwd: Path | None) -> tuple[bool, str]:
    return (cwd is None, str(cwd))


def read_session_cwd(session_path: Path) -> Path | None:
    # closing() shuts the file as soon as the cwd is found, instead of whenever the
    # half-read generator is garbage-collected; an open handle blocks moves on Windows.
    with closing(read_json_lines(session_path)) as lines:
        for line in lines:
            cwd = read_cwd(line) if line is not None else None
            if cwd is not None:
                return cwd
    return None
