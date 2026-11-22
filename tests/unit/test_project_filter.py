from pathlib import Path

import pytest

from agent_desk.domain.models import Project
from agent_desk.services.catalog import ProjectOverview
from agent_desk.tui.projects_screen import matches_filter


def overview_of(provider_id: str, cwd: str) -> ProjectOverview:
    project = Project(provider_id, Path("/data/storage"), Path(cwd))
    return ProjectOverview(project, session_count=1, last_activity=None, size_bytes=0)


@pytest.mark.parametrize(
    ("filter_text", "expected"),
    [
        ("", True),
        ("webapp", True),
        ("WEBAPP", True),
        ("  webapp  ", True),
        ("codex", True),
        ("api", False),
    ],
    ids=["empty", "lowercase", "uppercase", "padded", "by-provider", "no-match"],
)
def test_filter_matches_provider_or_project_ignoring_case(filter_text: str, expected: bool) -> None:
    overview = overview_of("codex", "/work/WebApp")

    assert matches_filter(overview, filter_text) is expected
