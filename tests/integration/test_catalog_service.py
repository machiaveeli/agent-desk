import os
from datetime import UTC, datetime, timedelta
from pathlib import Path

from agent_desk.domain.errors import ProjectNotFound, ProviderNotFound
from agent_desk.domain.models import Session, TranscriptEntry
from agent_desk.providers.claude_code import ClaudeCodeProvider
from agent_desk.providers.codex import CodexProvider
from agent_desk.services.catalog import CatalogService
from fixtures.claude_tree import ClaudeTree, custom_title_line, user_line
from fixtures.codex_tree import CodexTree

SESSION_A = "00000000-0000-4000-8000-00000000000a"
SESSION_B = "00000000-0000-4000-8000-00000000000b"
SESSION_C = "00000000-0000-4000-8000-00000000000c"
CODEX_SESSION = "00000000-0000-4000-8000-0000000000c1"
CWD = "/work/app"
CODEX_CREATED = datetime(2026, 1, 1, 10, 0, 0)
MODIFIED_AT = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)


def at_minute(minute: int) -> datetime:
    return datetime(2026, 1, 1, 10, minute, tzinfo=UTC)


def make_catalog(*trees: ClaudeTree) -> CatalogService:
    return CatalogService([ClaudeCodeProvider(root=tree.root) for tree in trees])


def make_tree(tmp_path: Path, name: str) -> ClaudeTree:
    return ClaudeTree(tmp_path / name / ".claude")


def test_project_overview_sums_up_its_sessions(claude_tree: ClaudeTree) -> None:
    project_dir = claude_tree.add_project(CWD)
    first = claude_tree.add_session(project_dir, SESSION_A, [user_line("a", cwd=CWD, minute=5)])
    second = claude_tree.add_session(project_dir, SESSION_B, [user_line("b", cwd=CWD, minute=9)])

    [overview] = make_catalog(claude_tree).list_projects().projects

    assert (overview.project.cwd, overview.session_count, overview.last_activity) == (
        Path(CWD),
        2,
        at_minute(9),
    )
    assert overview.size_bytes == first.stat().st_size + second.stat().st_size


def test_project_without_sessions_has_an_empty_overview(claude_tree: ClaudeTree) -> None:
    claude_tree.add_memory(claude_tree.add_project(CWD), "notes.md", "remember")

    [overview] = make_catalog(claude_tree).list_projects().projects

    assert (overview.session_count, overview.last_activity, overview.size_bytes) == (0, None, 0)


def test_projects_are_listed_by_last_activity_with_undated_ones_last(
    claude_tree: ClaudeTree,
) -> None:
    # Folder names run in the opposite order, so the result cannot come from discovery order.
    claude_tree.add_session(claude_tree.add_project("/a"), SESSION_A, [custom_title_line("t")])
    for cwd, session_id, minute in [("/b", SESSION_B, 1), ("/c", SESSION_C, 30)]:
        lines = [user_line("hi", cwd=cwd, minute=minute)]
        claude_tree.add_session(claude_tree.add_project(cwd), session_id, lines)

    catalog = make_catalog(claude_tree).list_projects()

    labels = [overview.project.storage_dir.name for overview in catalog.projects]
    assert labels == ["-c", "-b", "-a"]


def test_a_missing_provider_is_reported_and_the_others_still_listed(
    tmp_path: Path, claude_tree: ClaudeTree
) -> None:
    claude_tree.add_project(CWD)
    missing = make_tree(tmp_path, "missing")

    catalog = make_catalog(missing, claude_tree).list_projects()

    assert catalog.missing_providers == [ProviderNotFound("claude-code", missing.root)]
    assert [overview.project.storage_dir.name for overview in catalog.projects] == ["-work-app"]


def test_sessions_are_those_of_the_requested_cwd(claude_tree: ClaudeTree) -> None:
    # Both cwds are encoded to the same folder name, so the folder alone cannot tell them apart.
    project_dir = claude_tree.add_project("/work/my-app")
    claude_tree.add_session(project_dir, SESSION_A, [user_line("a", cwd="/work/my-app")])
    claude_tree.add_session(project_dir, SESSION_B, [user_line("b", cwd="/work/my/app")])

    result = make_catalog(claude_tree).list_sessions(Path("/work/my/app"))

    assert isinstance(result, list)
    assert [summary.session.session_id for summary in result] == [SESSION_B]


def test_sessions_from_every_provider_are_merged_most_recent_first(tmp_path: Path) -> None:
    first, second = make_tree(tmp_path, "first"), make_tree(tmp_path, "second")
    first.add_session(first.add_project(CWD), SESSION_A, [user_line("a", cwd=CWD, minute=1)])
    second.add_session(second.add_project(CWD), SESSION_B, [user_line("b", cwd=CWD, minute=2)])
    first.add_session(first.add_project(CWD), SESSION_C, [custom_title_line("undated")])

    result = make_catalog(first, second).list_sessions(Path(CWD))

    assert isinstance(result, list)
    assert [summary.session.session_id for summary in result] == [SESSION_B, SESSION_A, SESSION_C]


def test_unknown_cwd_is_project_not_found(tmp_path: Path, claude_tree: ClaudeTree) -> None:
    claude_tree.add_project(CWD)
    missing = make_tree(tmp_path, "missing")

    result = make_catalog(missing, claude_tree).list_sessions(Path("/elsewhere"))

    assert result == ProjectNotFound(Path("/elsewhere"))


def test_project_sessions_come_from_that_project_only_most_recent_first(
    claude_tree: ClaudeTree, codex_tree: CodexTree
) -> None:
    project_dir = claude_tree.add_project(CWD)
    claude_tree.add_session(project_dir, SESSION_A, [user_line("a", cwd=CWD, minute=1)])
    claude_tree.add_session(project_dir, SESSION_B, [user_line("b", cwd=CWD, minute=2)])
    # Same cwd, other provider: a separate project in the projects list.
    codex_tree.add_session(CODEX_SESSION, cwd=CWD, created=CODEX_CREATED, lines=[])
    catalog = CatalogService(
        [ClaudeCodeProvider(root=claude_tree.root), CodexProvider(root=codex_tree.root)]
    )
    [claude_project] = [
        overview.project
        for overview in catalog.list_projects().projects
        if overview.project.provider_id == "claude-code"
    ]

    summaries = catalog.list_project_sessions(claude_project)

    assert [summary.session.session_id for summary in summaries] == [SESSION_B, SESSION_A]


def catalog_at(codex_tree: CodexTree, moment: datetime) -> CatalogService:
    """Claude first, so a lookup that ignores the provider id would ask the wrong one."""
    codex = CodexProvider(root=codex_tree.root, now=lambda: moment)
    return CatalogService([ClaudeCodeProvider(root=codex_tree.root), codex])


def test_is_active_asks_the_session_provider(codex_tree: CodexTree) -> None:
    path = codex_tree.add_session(CODEX_SESSION, cwd=CWD, created=CODEX_CREATED, lines=[])
    os.utime(path, (MODIFIED_AT.timestamp(), MODIFIED_AT.timestamp()))
    session = Session("codex", CODEX_SESSION, path, None, Path(CWD))
    long_after = MODIFIED_AT + timedelta(hours=1)

    assert catalog_at(codex_tree, MODIFIED_AT).is_active(session)
    assert not catalog_at(codex_tree, long_after).is_active(session)


def test_transcript_is_read_by_the_session_provider(claude_tree: ClaudeTree) -> None:
    project_dir = claude_tree.add_project(CWD)
    claude_tree.add_session(project_dir, SESSION_A, [user_line("hello", cwd=CWD)])
    catalog = make_catalog(claude_tree)
    [summary] = catalog.list_project_sessions(catalog.list_projects().projects[0].project)

    entries = list(catalog.read_transcript(summary.session))

    assert entries == [TranscriptEntry("user", "hello")]
