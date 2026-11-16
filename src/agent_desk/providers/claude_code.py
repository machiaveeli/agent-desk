from contextlib import closing
from dataclasses import dataclass
from pathlib import Path

from agent_desk.config import CLAUDE_PROVIDER_ID
from agent_desk.domain.errors import ProviderNotFound
from agent_desk.domain.models import Project
from agent_desk.providers.jsonl import read_json_lines

PROJECTS_DIR_NAME = "projects"
SESSION_FILE_PATTERN = "*.jsonl"


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
        """One project per distinct cwd. The folder name is a lossy encoding of the cwd, so two
        cwds can share a folder; a folder with no known cwd is still listed (it may hold memory)."""
        session_cwds = (read_session_cwd(path) for path in storage_dir.glob(SESSION_FILE_PATTERN))
        cwds = sorted({cwd for cwd in session_cwds if cwd is not None}, key=str)
        if not cwds:
            return [Project(self.provider_id, storage_dir, None)]
        return [Project(self.provider_id, storage_dir, cwd) for cwd in cwds]


def read_session_cwd(session_path: Path) -> Path | None:
    # closing() shuts the file as soon as the cwd is found, instead of whenever the
    # half-read generator is garbage-collected; an open handle blocks moves on Windows.
    with closing(read_json_lines(session_path)) as lines:
        for line in lines:
            if line is None:
                continue
            cwd = line.get("cwd")
            if isinstance(cwd, str) and cwd:
                return Path(cwd)
    return None
