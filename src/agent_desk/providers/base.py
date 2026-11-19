from collections.abc import Iterator
from typing import Protocol

from agent_desk.domain.errors import ProviderNotFound
from agent_desk.domain.models import Project, Session, SessionSummary, TranscriptEntry


class Provider(Protocol):
    """What the services need from one AI CLI's folder on disk. Every method only reads."""

    @property
    def provider_id(self) -> str: ...

    def discover_projects(self) -> list[Project] | ProviderNotFound: ...

    def list_sessions(self, project: Project) -> list[SessionSummary]: ...

    def read_transcript(self, session: Session) -> Iterator[TranscriptEntry]: ...

    def is_active(self, session: Session) -> bool: ...

    def resume_command(self, session: Session) -> list[str]:
        """The argv that resumes the session in the provider's own CLI. argv[0] is the bare
        executable name; the caller finds it on PATH."""
        ...
