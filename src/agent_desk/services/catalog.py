"""Joins every provider into one catalog of projects and sessions. It only reads."""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from agent_desk.domain.errors import ProjectNotFound, ProviderNotFound, UnknownProvider
from agent_desk.domain.models import Project, Session, SessionSummary
from agent_desk.providers.base import Provider

UNDATED = datetime.min.replace(tzinfo=UTC)


@dataclass(frozen=True)
class ProjectOverview:
    """A project with totals over its sessions. `last_activity` is None without dated sessions."""

    project: Project
    session_count: int
    last_activity: datetime | None
    size_bytes: int


@dataclass(frozen=True)
class ProjectCatalog:
    projects: list[ProjectOverview]
    # Reported, not fatal: someone who never used one of the CLIs simply has no folder for it.
    missing_providers: list[ProviderNotFound]


@dataclass(frozen=True)
class FoundSession:
    """A session together with the provider that owns it, which knows how to act on it."""

    provider: Provider
    summary: SessionSummary


@dataclass(frozen=True)
class CatalogService:
    providers: Sequence[Provider]

    def only_provider(self, provider_id: str) -> "CatalogService | UnknownProvider":
        """The same catalog narrowed to one provider, for the `--provider` filter."""
        selected = [provider for provider in self.providers if provider.provider_id == provider_id]
        if not selected:
            known_ids = tuple(provider.provider_id for provider in self.providers)
            return UnknownProvider(provider_id, known_ids)
        return CatalogService(selected)

    def list_projects(self) -> ProjectCatalog:
        """Most recent activity first; projects without dated sessions come last."""
        overviews: list[ProjectOverview] = []
        missing: list[ProviderNotFound] = []
        for provider in self.providers:
            projects = provider.discover_projects()
            if isinstance(projects, ProviderNotFound):
                missing.append(projects)
                continue
            overviews += [summarize_project(project, provider) for project in projects]
        overviews.sort(key=lambda overview: overview.last_activity or UNDATED, reverse=True)
        return ProjectCatalog(overviews, missing)

    def list_sessions(self, cwd: Path) -> list[SessionSummary] | ProjectNotFound:
        """The sessions of every project with this cwd, across providers, most recent first."""
        is_known = False
        summaries: list[SessionSummary] = []
        for provider in self.providers:
            projects = provider.discover_projects()
            if isinstance(projects, ProviderNotFound):
                continue
            for project in projects:
                if project.cwd == cwd:
                    is_known = True
                    summaries += provider.list_sessions(project)
        if not is_known:
            return ProjectNotFound(cwd)
        return sort_most_recent_first(summaries)

    def list_project_sessions(self, project: Project) -> list[SessionSummary]:
        """The sessions of this one project, as the projects list shows it. Providers already
        return them most recent first."""
        return self.provider_for(project.provider_id).list_sessions(project)

    def is_active(self, session: Session) -> bool:
        return self.provider_for(session.provider_id).is_active(session)

    def provider_for(self, provider_id: str) -> Provider:
        """Sessions and projects always come from this catalog, so a miss is a bug."""
        for provider in self.providers:
            if provider.provider_id == provider_id:
                return provider
        raise LookupError(f"no provider with id {provider_id!r} in this catalog")

    def find_session(self, session_id: str) -> FoundSession | None:
        for provider in self.providers:
            projects = provider.discover_projects()
            if isinstance(projects, ProviderNotFound):
                continue
            for project in projects:
                for summary in provider.list_sessions(project):
                    if summary.session.session_id == session_id:
                        return FoundSession(provider, summary)
        return None


def sort_most_recent_first(summaries: list[SessionSummary]) -> list[SessionSummary]:
    """Undated sessions come last."""
    return sorted(summaries, key=lambda summary: summary.ended_at or UNDATED, reverse=True)


def summarize_project(project: Project, provider: Provider) -> ProjectOverview:
    summaries = provider.list_sessions(project)
    end_dates = [summary.ended_at for summary in summaries if summary.ended_at is not None]
    return ProjectOverview(
        project=project,
        session_count=len(summaries),
        last_activity=max(end_dates, default=None),
        size_bytes=sum(summary.size_bytes for summary in summaries),
    )
