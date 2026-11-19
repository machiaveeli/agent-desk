from datetime import datetime
from pathlib import Path

from agent_desk.cli.main import build_catalog
from agent_desk.config import Config
from agent_desk.domain.errors import ProviderNotFound
from agent_desk.providers.codex import CodexProvider
from fixtures.claude_tree import ClaudeTree, user_line
from fixtures.codex_tree import CodexTree, user_message

CLAUDE_SESSION = "00000000-0000-4000-8000-000000000001"
CODEX_SESSION = "00000000-0000-4000-8000-0000000000c1"
CWD = "/work/app"
CREATED = datetime(2026, 1, 1, 10, 0, 0)
TRASH_RETENTION_DAYS = 30
CODEX_THRESHOLD_MINUTES = 25


def make_config(claude_tree: ClaudeTree, codex_tree: CodexTree) -> Config:
    return Config(
        claude_root=claude_tree.root,
        codex_root=codex_tree.root,
        trash_retention_days=TRASH_RETENTION_DAYS,
        codex_active_threshold_minutes=CODEX_THRESHOLD_MINUTES,
    )


def test_catalog_joins_claude_and_codex_projects_of_the_same_cwd(
    claude_tree: ClaudeTree, codex_tree: CodexTree
) -> None:
    project_dir = claude_tree.add_project(CWD)
    claude_tree.add_session(project_dir, CLAUDE_SESSION, [user_line("from claude", cwd=CWD)])
    codex_tree.add_session(
        CODEX_SESSION, cwd=CWD, created=CREATED, lines=[user_message("from codex")]
    )
    catalog = build_catalog(make_config(claude_tree, codex_tree))

    projects = catalog.list_projects()
    sessions = catalog.list_sessions(Path(CWD))

    assert sorted(overview.project.provider_id for overview in projects.projects) == [
        "claude-code",
        "codex",
    ]
    assert projects.missing_providers == []
    assert isinstance(sessions, list)
    assert sorted(summary.session.session_id for summary in sessions) == [
        CLAUDE_SESSION,
        CODEX_SESSION,
    ]


def test_catalog_reports_each_missing_provider_root(
    claude_tree: ClaudeTree, codex_tree: CodexTree
) -> None:
    catalog = build_catalog(make_config(claude_tree, codex_tree))

    assert catalog.list_projects().missing_providers == [
        ProviderNotFound("claude-code", claude_tree.root),
        ProviderNotFound("codex", codex_tree.root),
    ]


def test_codex_provider_gets_the_configured_active_threshold(
    claude_tree: ClaudeTree, codex_tree: CodexTree
) -> None:
    catalog = build_catalog(make_config(claude_tree, codex_tree))

    [codex] = [provider for provider in catalog.providers if provider.provider_id == "codex"]

    assert isinstance(codex, CodexProvider)
    assert codex.active_threshold_minutes == CODEX_THRESHOLD_MINUTES
