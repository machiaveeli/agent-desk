import json
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path

import pytest

from agent_desk.domain.errors import TrashError
from agent_desk.domain.models import SessionSummary, TrashEntry, TrashItem
from agent_desk.providers.claude_code import ClaudeCodeProvider
from agent_desk.providers.codex import CodexProvider
from agent_desk.services.catalog import CatalogService
from agent_desk.services.trash import Mover, TrashService, move_path
from fixtures.claude_tree import ClaudeTree, custom_title_line, user_line
from fixtures.codex_tree import CodexTree, user_message
from fixtures.file_tree import snapshot

SESSION_ID = "3f2a9c1e-0000-4000-8000-000000000001"
CODEX_SESSION_ID = "0a1b2c3d-0000-4000-8000-0000000000c1"
CWD = "/work/app"
TITLE = "Fix the login bug"
SUBAGENT_TEXT = "{}\n"
# The two files add_claude_session writes inside the sibling folder.
SIBLING_SIZE = len(SUBAGENT_TEXT) + len(json.dumps({"customTitle": TITLE}))
NOW = datetime(2026, 11, 23, 14, 5, 12, 345678, tzinfo=UTC)
ENTRY_ID = "20261123T140512Z-3f2a9c1e"


class FailingMove:
    """Moves like the real one until `fail_on` is reached, then raises like a full disk."""

    def __init__(self, fail_on: str) -> None:
        self.fail_on = fail_on

    def __call__(self, source: Path, target: Path) -> None:
        if source.name == self.fail_on:
            raise OSError("simulated failure")
        source.rename(target)


@pytest.fixture
def trash_root(tmp_path: Path) -> Path:
    return tmp_path / "data" / "trash"


def make_service(trash_root: Path, move: Mover = move_path) -> TrashService:
    return TrashService(root=trash_root, is_active=lambda _: False, now=lambda: NOW, move=move)


def add_claude_session(claude_tree: ClaudeTree) -> SessionSummary:
    project_dir = claude_tree.add_project(CWD)
    claude_tree.add_session(
        project_dir, SESSION_ID, [user_line("hi", cwd=CWD), custom_title_line(TITLE)]
    )
    claude_tree.add_sibling_file(project_dir, SESSION_ID, "subagents/agent-1.jsonl", SUBAGENT_TEXT)
    claude_tree.add_sibling_custom_title(project_dir, SESSION_ID, TITLE)
    return only_session(CatalogService([ClaudeCodeProvider(root=claude_tree.root)]))


def only_session(catalog: CatalogService) -> SessionSummary:
    [overview] = catalog.list_projects().projects
    [summary] = catalog.list_project_sessions(overview.project)
    return summary


def stored_files(trash_root: Path) -> Path:
    return trash_root / ENTRY_ID / "files"


def read_manifest(trash_root: Path) -> object:
    return json.loads((trash_root / ENTRY_ID / "manifest.json").read_bytes())


def test_the_session_file_and_its_sibling_folder_leave_the_provider_folder(
    claude_tree: ClaudeTree, trash_root: Path
) -> None:
    summary = add_claude_session(claude_tree)

    sibling_dir = summary.session.sibling_dir
    assert sibling_dir is not None

    make_service(trash_root).trash(summary)

    assert (summary.session.path.exists(), sibling_dir.exists()) == (False, False)


def test_the_stored_copy_is_byte_identical_to_the_original(
    claude_tree: ClaudeTree, trash_root: Path
) -> None:
    summary = add_claude_session(claude_tree)
    project_dir = summary.session.path.parent
    before = snapshot(project_dir)

    make_service(trash_root).trash(summary)

    assert snapshot(stored_files(trash_root)) == before


def test_the_entry_describes_what_was_moved_and_from_where(
    claude_tree: ClaudeTree, trash_root: Path
) -> None:
    summary = add_claude_session(claude_tree)
    session = summary.session
    assert session.sibling_dir is not None
    file_size = session.path.stat().st_size

    entry = make_service(trash_root).trash(summary)

    assert entry == TrashEntry(
        entry_id=ENTRY_ID,
        state="complete",
        provider_id="claude-code",
        session_id=SESSION_ID,
        cwd=Path(CWD),
        title=TITLE,
        trashed_at=NOW.replace(microsecond=0),
        items=(
            TrashItem(session.path, f"{SESSION_ID}.jsonl", "file", file_size),
            TrashItem(session.sibling_dir, SESSION_ID, "dir", SIBLING_SIZE),
        ),
    )


def test_the_manifest_on_disk_follows_the_approved_format(
    claude_tree: ClaudeTree, trash_root: Path
) -> None:
    summary = add_claude_session(claude_tree)
    session = summary.session
    assert session.sibling_dir is not None
    file_size = session.path.stat().st_size

    make_service(trash_root).trash(summary)

    assert read_manifest(trash_root) == {
        "version": 1,
        "entry_id": ENTRY_ID,
        "state": "complete",
        "provider_id": "claude-code",
        "session_id": SESSION_ID,
        "cwd": str(Path(CWD)),
        "title": TITLE,
        "trashed_at": "2026-11-23T14:05:12Z",
        "items": [
            {
                "original_path": str(session.path),
                "stored_name": f"{SESSION_ID}.jsonl",
                "kind": "file",
                "size_bytes": file_size,
            },
            {
                "original_path": str(session.sibling_dir),
                "stored_name": SESSION_ID,
                "kind": "dir",
                "size_bytes": SIBLING_SIZE,
            },
        ],
    }


def test_a_codex_session_is_only_its_rollout_and_the_name_index_is_left_alone(
    codex_tree: CodexTree, trash_root: Path
) -> None:
    rollout = codex_tree.add_session(
        CODEX_SESSION_ID,
        cwd=CWD,
        created=datetime(2026, 1, 1, 10, 0, 0),
        lines=[user_message("hi", minute=1)],
    )
    index = codex_tree.add_thread_name(CODEX_SESSION_ID, TITLE, minute=2)
    index_before = index.read_bytes()
    summary = only_session(CatalogService([CodexProvider(root=codex_tree.root)]))

    entry = make_service(trash_root).trash(summary)

    assert isinstance(entry, TrashEntry)
    assert (entry.entry_id, [item.stored_name for item in entry.items]) == (
        "20261123T140512Z-0a1b2c3d",
        [rollout.name],
    )
    assert (rollout.exists(), index.read_bytes()) == (False, index_before)


def test_a_session_that_already_has_an_entry_is_refused_and_nothing_moves(
    claude_tree: ClaudeTree, trash_root: Path
) -> None:
    summary = add_claude_session(claude_tree)
    with pytest.raises(OSError, match="simulated failure"):
        make_service(trash_root, move=FailingMove(fail_on=SESSION_ID)).trash(summary)
    before = snapshot(claude_tree.root), snapshot(trash_root)

    result = make_service(trash_root).trash(summary)

    assert isinstance(result, TrashError)
    assert result.reason == "already_trashed"
    assert (snapshot(claude_tree.root), snapshot(trash_root)) == before


def test_a_move_that_fails_halfway_leaves_a_pending_entry_listing_every_item(
    claude_tree: ClaudeTree, trash_root: Path
) -> None:
    summary = add_claude_session(claude_tree)

    with pytest.raises(OSError, match="simulated failure"):
        make_service(trash_root, move=FailingMove(fail_on=SESSION_ID)).trash(summary)

    manifest = read_manifest(trash_root)
    assert isinstance(manifest, dict)
    assert (manifest["state"], len(manifest["items"])) == ("pending", 2)
    assert sorted(snapshot(stored_files(trash_root))) == [f"{SESSION_ID}.jsonl"]


def test_sessions_trashed_in_the_same_second_with_the_same_id_prefix_get_distinct_entries(
    claude_tree: ClaudeTree, trash_root: Path
) -> None:
    project_dir = claude_tree.add_project(CWD)
    session_ids = [SESSION_ID, f"{SESSION_ID[:-1]}2", f"{SESSION_ID[:-1]}3"]
    for session_id in session_ids:
        claude_tree.add_session(project_dir, session_id, [user_line("hi", cwd=CWD)])
    catalog = CatalogService([ClaudeCodeProvider(root=claude_tree.root)])
    [overview] = catalog.list_projects().projects
    service = make_service(trash_root)

    entries = [
        service.trash(summary) for summary in catalog.list_project_sessions(overview.project)
    ]

    assert sorted(entry.entry_id for entry in entries if isinstance(entry, TrashEntry)) == [
        ENTRY_ID,
        f"{ENTRY_ID}-2",
        f"{ENTRY_ID}-3",
    ]


def test_the_entry_time_is_stored_in_utc_whatever_the_clock_timezone(
    claude_tree: ClaudeTree, trash_root: Path
) -> None:
    summary = add_claude_session(claude_tree)
    local_now = NOW.astimezone(timezone(timedelta(hours=-3)))
    service = TrashService(root=trash_root, is_active=lambda _: False, now=lambda: local_now)

    entry = service.trash(summary)

    assert isinstance(entry, TrashEntry)
    assert (entry.entry_id, entry.trashed_at.utcoffset()) == (ENTRY_ID, timedelta(0))
