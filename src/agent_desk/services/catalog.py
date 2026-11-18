"""Joins every provider into one catalog of projects and sessions. It only reads."""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from agent_desk.domain.errors import ProjectNotFound, ProviderNotFound
from agent_desk.domain.models import Project, SessionSummary
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
class CatalogService:
    providers: Sequence[Provider]

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
