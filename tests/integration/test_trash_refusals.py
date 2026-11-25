"""Success criterion 4: a refused trash changes nothing on disk, in the provider or the trash."""

import os
import shutil
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from agent_desk.domain.errors import TrashError
from agent_desk.domain.models import SessionSummary
from agent_desk.providers.claude_code import ClaudeCodeProvider
from agent_desk.providers.codex import CodexProvider
from agent_desk.providers.processes import NOT_RUNNING, ProcessState
from agent_desk.services.catalog import CatalogService
from agent_desk.services.trash import TrashService
from fixtures.claude_tree import FAKE_PROC_START, ClaudeTree, user_line
from fixtures.codex_tree import CodexTree, user_message
from fixtures.file_tree import TreeSnapshot, snapshot

SESSION_ID = "3f2a9c1e-0000-4000-8000-000000000001"
CWD = "/work/app"
PID = 4242
NOW = datetime(2026, 11, 23, 14, 5, 12, tzinfo=UTC)
CODEX_THRESHOLD_MINUTES = 10


@pytest.fixture
def trash_root(tmp_path: Path) -> Path:
    return tmp_path / "data" / "trash"


def claude_catalog(claude_tree: ClaudeTree, *, running: ProcessState) -> CatalogService:
    provider = ClaudeCodeProvider(
        root=claude_tree.root, inspect_process=lambda pid: running if pid == PID else NOT_RUNNING
    )
    return CatalogService([provider])


def add_claude_session(claude_tree: ClaudeTree) -> None:
    project_dir = claude_tree.add_project(CWD)
    claude_tree.add_session(project_dir, SESSION_ID, [user_line("hi", cwd=CWD)])
    claude_tree.add_sibling_file(project_dir, SESSION_ID, "subagents/agent-1.jsonl", "{}\n")


def only_session(catalog: CatalogService) -> SessionSummary:
    [overview] = catalog.list_projects().projects
    [summary] = catalog.list_project_sessions(overview.project)
    return summary


def trash_with(catalog: CatalogService, trash_root: Path, summary: SessionSummary) -> object:
    service = TrashService(root=trash_root, is_active=catalog.is_active, now=lambda: NOW)
    return service.trash(summary)


def disk_state(provider_root: Path, trash_root: Path) -> tuple[TreeSnapshot, bool]:
    return snapshot(provider_root.parent), trash_root.exists()


def test_a_claude_session_open_in_a_live_process_is_refused_and_nothing_changes(
    claude_tree: ClaudeTree, trash_root: Path
) -> None:
    add_claude_session(claude_tree)
    claude_tree.add_active_session_file(pid=PID, session_id=SESSION_ID, cwd=CWD)
    running = ProcessState(is_running=True, start_marker=FAKE_PROC_START)
    catalog = claude_catalog(claude_tree, running=running)
    summary = only_session(catalog)
    before = disk_state(claude_tree.root, trash_root)

    result = trash_with(catalog, trash_root, summary)

    assert isinstance(result, TrashError)
    assert result.reason == "session_active"
    assert disk_state(claude_tree.root, trash_root) == before


def test_a_codex_session_written_moments_ago_is_refused_and_nothing_changes(
    codex_tree: CodexTree, trash_root: Path
) -> None:
    rollout = codex_tree.add_session(
        SESSION_ID, cwd=CWD, created=datetime(2026, 1, 1, 10, 0, 0), lines=[user_message("hi")]
    )
    modified_at = NOW - timedelta(minutes=1)
    os.utime(rollout, (modified_at.timestamp(), modified_at.timestamp()))
    provider = CodexProvider(
        root=codex_tree.root, active_threshold_minutes=CODEX_THRESHOLD_MINUTES, now=lambda: NOW
    )
    catalog = CatalogService([provider])
    summary = only_session(catalog)
    before = disk_state(codex_tree.root, trash_root)

    result = trash_with(catalog, trash_root, summary)

    assert isinstance(result, TrashError)
    assert result.reason == "session_active"
    assert disk_state(codex_tree.root, trash_root) == before


def test_a_session_whose_file_vanished_since_it_was_listed_is_refused_and_nothing_changes(
    claude_tree: ClaudeTree, trash_root: Path
) -> None:
    add_claude_session(claude_tree)
    catalog = claude_catalog(claude_tree, running=NOT_RUNNING)
    summary = only_session(catalog)
    summary.session.path.unlink()
    before = disk_state(claude_tree.root, trash_root)

    result = trash_with(catalog, trash_root, summary)

    assert isinstance(result, TrashError)
    assert result.reason == "not_found"
    assert disk_state(claude_tree.root, trash_root) == before


def test_a_session_whose_sibling_folder_vanished_since_it_was_listed_is_refused(
    claude_tree: ClaudeTree, trash_root: Path
) -> None:
    add_claude_session(claude_tree)
    catalog = claude_catalog(claude_tree, running=NOT_RUNNING)
    summary = only_session(catalog)
    assert summary.session.sibling_dir is not None
    shutil.rmtree(summary.session.sibling_dir)
    before = disk_state(claude_tree.root, trash_root)

    result = trash_with(catalog, trash_root, summary)

    assert result == TrashError("not_found", f"{SESSION_ID} no longer exists.")
    assert disk_state(claude_tree.root, trash_root) == before


def test_the_refusal_messages_tell_the_user_what_to_do(
    claude_tree: ClaudeTree, trash_root: Path
) -> None:
    add_claude_session(claude_tree)
    catalog = claude_catalog(claude_tree, running=NOT_RUNNING)
    summary = only_session(catalog)
    service = TrashService(root=trash_root, is_active=lambda _: True, now=lambda: NOW)

    result = service.trash(summary)

    assert result == TrashError(
        "session_active", "the session is still open; close it before moving it to the trash."
    )
