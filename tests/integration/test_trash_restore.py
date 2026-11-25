import errno
import json
import shutil
from datetime import UTC, datetime
from functools import partial
from pathlib import Path

import pytest

from agent_desk.domain.errors import TrashError
from agent_desk.domain.models import SessionSummary, TrashEntry
from agent_desk.providers.claude_code import ClaudeCodeProvider
from agent_desk.providers.codex import CodexProvider
from agent_desk.services.catalog import CatalogService
from agent_desk.services.file_move import move_path
from agent_desk.services.trash import TrashService
from fixtures.claude_tree import ClaudeTree, custom_title_line, user_line
from fixtures.codex_tree import CodexTree, user_message
from fixtures.file_tree import TreeSnapshot, snapshot

SESSION_ID = "3f2a9c1e-0000-4000-8000-000000000001"
CWD = "/work/app"
TITLE = "Fix the login bug"
NOW = datetime(2026, 11, 23, 14, 5, 12, tzinfo=UTC)
RETENTION_DAYS = 30
ENTRY_ID = "20261123T140512Z-3f2a9c1e"


class FailingMove:
    """Moves like the real one until `fail_on` is reached, then raises like a full disk."""

    def __init__(self, fail_on: str) -> None:
        self.fail_on = fail_on

    def __call__(self, source: Path, target: Path) -> None:
        if source.name == self.fail_on:
            raise OSError("simulated failure")
        source.rename(target)


def cross_device_rename(source: Path, target: Path) -> None:
    raise OSError(errno.EXDEV, "Invalid cross-device link")


@pytest.fixture
def trash_root(tmp_path: Path) -> Path:
    return tmp_path / "data" / "trash"


@pytest.fixture
def service(trash_root: Path) -> TrashService:
    return TrashService(
        root=trash_root, is_active=lambda _: False, now=lambda: NOW, retention_days=RETENTION_DAYS
    )


def claude_catalog(claude_tree: ClaudeTree) -> CatalogService:
    return CatalogService([ClaudeCodeProvider(root=claude_tree.root)])


def add_claude_session(claude_tree: ClaudeTree) -> SessionSummary:
    project_dir = claude_tree.add_project(CWD)
    claude_tree.add_session(
        project_dir, SESSION_ID, [user_line("hi", cwd=CWD), custom_title_line(TITLE)]
    )
    claude_tree.add_sibling_file(project_dir, SESSION_ID, "subagents/agent-1.jsonl", "{}\n")
    claude_tree.add_sibling_custom_title(project_dir, SESSION_ID, TITLE)
    return only_session(claude_catalog(claude_tree))


def only_session(catalog: CatalogService) -> SessionSummary:
    [overview] = catalog.list_projects().projects
    [summary] = catalog.list_project_sessions(overview.project)
    return summary


def disk_state(claude_tree: ClaudeTree, trash_root: Path) -> tuple[TreeSnapshot, TreeSnapshot]:
    return snapshot(claude_tree.root), snapshot(trash_root)


def test_trash_then_restore_leaves_the_provider_folder_byte_identical(
    claude_tree: ClaudeTree, service: TrashService
) -> None:
    summary = add_claude_session(claude_tree)
    before = snapshot(claude_tree.root)
    service.trash(summary)

    restored = service.restore(ENTRY_ID)

    assert isinstance(restored, TrashEntry)
    assert snapshot(claude_tree.root) == before


def test_the_round_trip_is_byte_identical_when_the_trash_is_on_another_volume(
    claude_tree: ClaudeTree, trash_root: Path
) -> None:
    summary = add_claude_session(claude_tree)
    before = snapshot(claude_tree.root)
    service = TrashService(
        root=trash_root,
        is_active=lambda _: False,
        now=lambda: NOW,
        retention_days=RETENTION_DAYS,
        move=partial(move_path, rename=cross_device_rename),
    )
    service.trash(summary)

    service.restore(ENTRY_ID)

    assert (snapshot(claude_tree.root), snapshot(trash_root)) == (before, {})


def test_a_restored_entry_leaves_the_trash(
    claude_tree: ClaudeTree, service: TrashService, trash_root: Path
) -> None:
    service.trash(add_claude_session(claude_tree))

    service.restore(ENTRY_ID)

    assert snapshot(trash_root) == {}


def test_a_restored_session_is_listed_again_with_its_title(
    claude_tree: ClaudeTree, service: TrashService
) -> None:
    service.trash(add_claude_session(claude_tree))

    service.restore(ENTRY_ID)

    restored = only_session(claude_catalog(claude_tree))
    assert (restored.session.session_id, restored.title) == (SESSION_ID, TITLE)


def test_a_codex_session_comes_back_with_its_thread_name(
    codex_tree: CodexTree, service: TrashService
) -> None:
    codex_tree.add_session(
        SESSION_ID,
        cwd=CWD,
        created=datetime(2026, 1, 1, 10, 0, 0),
        lines=[user_message("hi", minute=1)],
    )
    codex_tree.add_thread_name(SESSION_ID, TITLE, minute=2)
    catalog = CatalogService([CodexProvider(root=codex_tree.root)])
    before = snapshot(codex_tree.root)
    service.trash(only_session(catalog))

    service.restore(ENTRY_ID)

    assert (snapshot(codex_tree.root), only_session(catalog).title) == (before, TITLE)


def test_the_project_folder_is_recreated_when_it_was_removed_meanwhile(
    claude_tree: ClaudeTree, service: TrashService
) -> None:
    summary = add_claude_session(claude_tree)
    before = snapshot(claude_tree.root)
    service.trash(summary)
    summary.session.path.parent.rmdir()

    service.restore(ENTRY_ID)

    assert snapshot(claude_tree.root) == before


def test_restore_refuses_to_overwrite_a_file_that_reappeared_and_changes_nothing(
    claude_tree: ClaudeTree, service: TrashService, trash_root: Path
) -> None:
    summary = add_claude_session(claude_tree)
    service.trash(summary)
    summary.session.path.write_bytes(b"a new session with the same id\n")
    before = disk_state(claude_tree, trash_root)

    result = service.restore(ENTRY_ID)

    assert isinstance(result, TrashError)
    assert result.reason == "conflict"
    assert str(summary.session.path) in result.detail
    assert disk_state(claude_tree, trash_root) == before


def test_restore_refuses_a_conflict_on_any_item_before_moving_the_others(
    claude_tree: ClaudeTree, service: TrashService, trash_root: Path
) -> None:
    summary = add_claude_session(claude_tree)
    assert summary.session.sibling_dir is not None
    service.trash(summary)
    summary.session.sibling_dir.mkdir()
    before = disk_state(claude_tree, trash_root)

    result = service.restore(ENTRY_ID)

    assert isinstance(result, TrashError)
    assert result.reason == "conflict"
    assert disk_state(claude_tree, trash_root) == before


def test_an_unreadable_manifest_is_reported_and_the_entry_stays_in_the_trash(
    claude_tree: ClaudeTree, service: TrashService, trash_root: Path
) -> None:
    service.trash(add_claude_session(claude_tree))
    (trash_root / ENTRY_ID / "manifest.json").write_bytes(b'{"version": 1, "entry_')
    before = disk_state(claude_tree, trash_root)

    result = service.restore(ENTRY_ID)

    assert isinstance(result, TrashError)
    assert result.reason == "corrupted_manifest"
    assert disk_state(claude_tree, trash_root) == before


def test_a_manifest_copied_from_another_entry_is_reported_as_corrupted(
    claude_tree: ClaudeTree, service: TrashService, trash_root: Path
) -> None:
    service.trash(add_claude_session(claude_tree))
    shutil.copytree(trash_root / ENTRY_ID, trash_root / f"{ENTRY_ID}-copy")

    result = service.restore(f"{ENTRY_ID}-copy")

    assert isinstance(result, TrashError)
    assert result.reason == "corrupted_manifest"


def test_a_complete_entry_whose_stored_file_is_gone_is_reported_and_nothing_changes(
    claude_tree: ClaudeTree, service: TrashService, trash_root: Path
) -> None:
    service.trash(add_claude_session(claude_tree))
    (trash_root / ENTRY_ID / "files" / f"{SESSION_ID}.jsonl").unlink()
    before = disk_state(claude_tree, trash_root)

    result = service.restore(ENTRY_ID)

    assert isinstance(result, TrashError)
    assert result.reason == "missing_files"
    assert disk_state(claude_tree, trash_root) == before


@pytest.mark.parametrize(
    "entry_id",
    ["20200101T000000Z-00000000", "..", "../trash", "", f"{ENTRY_ID}/files"],
    ids=["unknown", "parent", "outside", "empty", "nested"],
)
def test_an_id_that_names_no_entry_is_reported_and_nothing_changes(
    claude_tree: ClaudeTree, service: TrashService, trash_root: Path, entry_id: str
) -> None:
    service.trash(add_claude_session(claude_tree))
    before = disk_state(claude_tree, trash_root)

    result = service.restore(entry_id)

    assert isinstance(result, TrashError)
    assert result.reason == "entry_not_found"
    assert disk_state(claude_tree, trash_root) == before


def test_an_entry_left_pending_by_a_crash_restores_everything_to_its_place(
    claude_tree: ClaudeTree, trash_root: Path, service: TrashService
) -> None:
    summary = add_claude_session(claude_tree)
    before = snapshot(claude_tree.root)
    crashing = TrashService(
        root=trash_root,
        is_active=lambda _: False,
        now=lambda: NOW,
        retention_days=RETENTION_DAYS,
        move=FailingMove(fail_on=SESSION_ID),
    )
    with pytest.raises(OSError, match="simulated failure"):
        crashing.trash(summary)
    manifest = json.loads((trash_root / ENTRY_ID / "manifest.json").read_bytes())
    assert manifest["state"] == "pending"

    result = service.restore(ENTRY_ID)

    assert isinstance(result, TrashEntry)
    assert (snapshot(claude_tree.root), snapshot(trash_root)) == (before, {})
