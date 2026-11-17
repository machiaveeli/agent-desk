import json
from collections.abc import Callable
from contextlib import closing
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from agent_desk.config import CLAUDE_PROVIDER_ID
from agent_desk.domain.errors import ProviderNotFound
from agent_desk.domain.models import Project, Session, SessionSummary
from agent_desk.providers.claude_summary import read_cwd, summarize_session
from agent_desk.providers.jsonl import read_json_lines
from agent_desk.providers.processes import ProcessState, inspect_process

PROJECTS_DIR_NAME = "projects"
SESSION_FILE_PATTERN = "*.jsonl"
SESSIONS_DIR_NAME = "sessions"
# Only `<pid>.json`. The `<pid>.<hash>.key` files beside them look like secrets, so they are
# never opened, not even to find out they are not JSON.
SESSION_RECORD_PATTERN = "*.json"
UNDATED = datetime.min.replace(tzinfo=UTC)


@dataclass(frozen=True)
class ClaudeCodeProvider:
    """Reads the Claude Code folder (`~/.claude` by default). It never writes."""

    root: Path
    # Injected so tests can decide which pids are alive without real processes.
    inspect_process: Callable[[int], ProcessState] = field(default=inspect_process)

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

    def is_active(self, session: Session) -> bool:
        """A Claude Code process still running this session, per its `sessions/<pid>.json`."""
        records = read_session_records(self.root / SESSIONS_DIR_NAME)
        return any(
            record.session_id == session.session_id
            and is_record_alive(record, self.inspect_process)
            for record in records
        )


@dataclass(frozen=True)
class SessionRecord:
    """The part of `sessions/<pid>.json` that tells whether a session is open."""

    pid: int
    session_id: str
    proc_start: str | None


def read_session_records(sessions_dir: Path) -> list[SessionRecord]:
    # glob() on a missing folder yields nothing, so no existence check is needed.
    records = (
        read_session_record(path) for path in sorted(sessions_dir.glob(SESSION_RECORD_PATTERN))
    )
    return [record for record in records if record is not None]


def read_session_record(path: Path) -> SessionRecord | None:
    try:
        content = json.loads(path.read_bytes())
    except (OSError, ValueError):
        return None
    if not isinstance(content, dict):
        return None
    pid = content.get("pid")
    session_id = content.get("sessionId")
    proc_start = content.get("procStart")
    # bool is a subclass of int in Python, so `true` would otherwise pass as pid 1.
    if isinstance(pid, bool) or not isinstance(pid, int) or not isinstance(session_id, str):
        return None
    return SessionRecord(pid, session_id, proc_start if isinstance(proc_start, str) else None)


def is_record_alive(record: SessionRecord, inspect: Callable[[int], ProcessState]) -> bool:
    state = inspect(record.pid)
    if not state.is_running:
        return False
    if state.start_marker is None or record.proc_start is None:
        # Without both start times the pid cannot be double-checked. Counting the session as
        # active is the safe side: active sessions are never modified.
        return True
    # A different start time means the OS gave this pid to a newer process.
    return state.start_marker == record.proc_start


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
