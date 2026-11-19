from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from agent_desk.config import CODEX_PROVIDER_ID
from agent_desk.domain.errors import ProviderNotFound
from agent_desk.domain.models import Project, Session, SessionSummary, TranscriptEntry
from agent_desk.providers.codex_rollout import list_rollout_files, read_rollout_meta
from agent_desk.providers.codex_summary import read_thread_names, summarize_rollout
from agent_desk.providers.codex_transcript import read_transcript_entries

SESSIONS_DIR_NAME = "sessions"
UNDATED = datetime.min.replace(tzinfo=UTC)


@dataclass(frozen=True)
class CodexProvider:
    """Reads the Codex folder (`~/.codex` by default). It never writes.

    Codex keeps every rollout under `sessions/YYYY/MM/DD/`, whatever the project, so every
    project shares that folder as its `storage_dir`; the cwd inside each rollout tells them
    apart.
    """

    root: Path

    @property
    def provider_id(self) -> str:
        return CODEX_PROVIDER_ID

    @property
    def sessions_dir(self) -> Path:
        return self.root / SESSIONS_DIR_NAME

    def discover_projects(self) -> list[Project] | ProviderNotFound:
        if not self.root.is_dir():
            return ProviderNotFound(self.provider_id, self.root)
        cwds = {cwd for _path, cwd in self.list_user_rollouts()}
        return [
            Project(self.provider_id, self.sessions_dir, cwd)
            for cwd in sorted(cwds, key=sort_key_for_cwd)
        ]

    def list_sessions(self, project: Project) -> list[SessionSummary]:
        """The project's sessions, most recent first; undated sessions come last."""
        thread_names = read_thread_names(self.root)
        summaries = [
            summarize_rollout(path, self.provider_id, thread_names)
            for path, cwd in self.list_user_rollouts()
            if cwd == project.cwd
        ]
        # Files come sorted by path (date, then time and id), and the sort is stable.
        return sorted(summaries, key=lambda summary: summary.ended_at or UNDATED, reverse=True)

    def read_transcript(self, session: Session) -> Iterator[TranscriptEntry]:
        return read_transcript_entries(session.path)

    def list_user_rollouts(self) -> list[tuple[Path, Path | None]]:
        """Each rollout with its cwd, leaving out the ones Codex started on its own (subagents,
        internal jobs). Only the first line is read, so this stays cheap."""
        rollouts = []
        for path in list_rollout_files(self.sessions_dir):
            meta = read_rollout_meta(path)
            if meta is not None and meta.is_non_root:
                continue
            rollouts.append((path, meta.cwd if meta is not None else None))
        return rollouts


def sort_key_for_cwd(cwd: Path | None) -> tuple[bool, str]:
    return (cwd is None, str(cwd))
