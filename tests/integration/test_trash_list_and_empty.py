from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from agent_desk.domain.models import SessionSummary, TrashEntry
from agent_desk.providers.claude_code import ClaudeCodeProvider
from agent_desk.services.catalog import CatalogService
from agent_desk.services.trash import ListedEntry, TrashService, UnreadableEntry
from fixtures.claude_tree import ClaudeTree, user_line
from fixtures.file_tree import snapshot

CWD = "/work/app"
RETENTION_DAYS = 30
TRASHED_AT = datetime(2026, 10, 1, 12, 0, 0, tzinfo=UTC)
OLD_ID = "00000000-0000-4000-8000-000000000001"
NEW_ID = "11111111-0000-4000-8000-000000000002"


class Clock:
    """A clock the test moves by hand."""

    def __init__(self, moment: datetime) -> None:
        self.moment = moment

    def __call__(self) -> datetime:
        return self.moment


@pytest.fixture
def clock() -> Clock:
    return Clock(TRASHED_AT)


@pytest.fixture
def trash_root(tmp_path: Path) -> Path:
    return tmp_path / "data" / "trash"


@pytest.fixture
def service(trash_root: Path, clock: Clock) -> TrashService:
    return TrashService(
        root=trash_root, is_active=lambda _: False, now=clock, retention_days=RETENTION_DAYS
    )


def add_sessions(claude_tree: ClaudeTree, *session_ids: str) -> dict[str, SessionSummary]:
    project_dir = claude_tree.add_project(CWD)
    for session_id in session_ids:
        claude_tree.add_session(project_dir, session_id, [user_line("hi", cwd=CWD)])
    catalog = CatalogService([ClaudeCodeProvider(root=claude_tree.root)])
    [overview] = catalog.list_projects().projects
    summaries = catalog.list_project_sessions(overview.project)
    return {summary.session.session_id: summary for summary in summaries}


def trash_one(service: TrashService, summary: SessionSummary) -> TrashEntry:
    entry = service.trash(summary)
    assert isinstance(entry, TrashEntry)
    return entry


@pytest.mark.parametrize(
    ("age", "is_expired"),
    [
        (timedelta(days=30) - timedelta(seconds=1), False),
        (timedelta(days=30), False),
        (timedelta(days=30, seconds=1), True),
    ],
    ids=["one-second-before", "exactly-30-days", "one-second-after"],
)
def test_an_entry_expires_once_it_is_older_than_the_retention(
    claude_tree: ClaudeTree, service: TrashService, clock: Clock, age: timedelta, is_expired: bool
) -> None:
    entry = trash_one(service, add_sessions(claude_tree, OLD_ID)[OLD_ID])
    clock.moment = TRASHED_AT + age

    assert service.list_entries().entries == [ListedEntry(entry, is_expired)]


def test_entries_are_listed_most_recent_first(
    claude_tree: ClaudeTree, service: TrashService, clock: Clock
) -> None:
    summaries = add_sessions(claude_tree, OLD_ID, NEW_ID)
    old = trash_one(service, summaries[OLD_ID])
    clock.moment = TRASHED_AT + timedelta(days=1)
    new = trash_one(service, summaries[NEW_ID])

    listed = [listed.entry for listed in service.list_entries().entries]

    assert listed == [new, old]


def test_an_entry_with_an_unreadable_manifest_is_listed_apart_with_the_reason(
    claude_tree: ClaudeTree, service: TrashService, trash_root: Path
) -> None:
    entry = trash_one(service, add_sessions(claude_tree, OLD_ID)[OLD_ID])
    (trash_root / entry.entry_id / "manifest.json").write_bytes(b"{")

    listing = service.list_entries()

    assert (listing.entries, listing.unreadable) == (
        [],
        [UnreadableEntry(entry.entry_id, "the manifest is not valid JSON")],
    )


def test_an_empty_or_missing_trash_lists_nothing(service: TrashService) -> None:
    listing = service.list_entries()

    assert (listing.entries, listing.unreadable) == ([], [])


def test_empty_plans_only_the_expired_entries(
    claude_tree: ClaudeTree, service: TrashService, clock: Clock
) -> None:
    summaries = add_sessions(claude_tree, OLD_ID, NEW_ID)
    old = trash_one(service, summaries[OLD_ID])
    clock.moment = TRASHED_AT + timedelta(days=20)
    trash_one(service, summaries[NEW_ID])
    clock.moment = TRASHED_AT + timedelta(days=31)

    assert service.plan_empty() == [old]


def test_empty_deletes_the_planned_entries_and_leaves_the_rest_untouched(
    claude_tree: ClaudeTree, service: TrashService, clock: Clock, trash_root: Path
) -> None:
    summaries = add_sessions(claude_tree, OLD_ID, NEW_ID)
    old = trash_one(service, summaries[OLD_ID])
    clock.moment = TRASHED_AT + timedelta(days=20)
    new = trash_one(service, summaries[NEW_ID])
    new_before = snapshot(trash_root / new.entry_id)
    clock.moment = TRASHED_AT + timedelta(days=31)

    deleted = service.empty(service.plan_empty())

    assert deleted == [old]
    assert sorted(path.name for path in trash_root.iterdir()) == [new.entry_id]
    assert snapshot(trash_root / new.entry_id) == new_before


def test_an_expired_entry_left_pending_by_a_crash_is_never_emptied(
    claude_tree: ClaudeTree, service: TrashService, clock: Clock, trash_root: Path
) -> None:
    entry = trash_one(service, add_sessions(claude_tree, OLD_ID)[OLD_ID])
    manifest = trash_root / entry.entry_id / "manifest.json"
    manifest.write_bytes(manifest.read_bytes().replace(b'"complete"', b'"pending"'))
    clock.moment = TRASHED_AT + timedelta(days=31)
    before = snapshot(trash_root)

    pending = replace(entry, state="pending")

    planned = service.plan_empty()
    deleted = service.empty([pending])

    assert (planned, deleted, snapshot(trash_root)) == ([], [], before)


def test_empty_skips_a_planned_entry_that_was_restored_in_the_meantime(
    claude_tree: ClaudeTree, service: TrashService, clock: Clock, trash_root: Path
) -> None:
    entry = trash_one(service, add_sessions(claude_tree, OLD_ID)[OLD_ID])
    clock.moment = TRASHED_AT + timedelta(days=31)
    plan = service.plan_empty()
    service.restore(entry.entry_id)

    assert (service.empty(plan), snapshot(trash_root)) == ([], {})


def test_empty_skips_an_entry_that_is_not_expired_even_when_asked(
    claude_tree: ClaudeTree, service: TrashService, clock: Clock, trash_root: Path
) -> None:
    entry = trash_one(service, add_sessions(claude_tree, OLD_ID)[OLD_ID])
    clock.moment = TRASHED_AT + timedelta(days=1)
    before = snapshot(trash_root)

    assert (service.empty([entry]), snapshot(trash_root)) == ([], before)


def test_a_retention_of_zero_days_expires_everything_trashed_before_now(
    claude_tree: ClaudeTree, trash_root: Path, clock: Clock
) -> None:
    service = TrashService(root=trash_root, is_active=lambda _: False, now=clock, retention_days=0)
    entry = trash_one(service, add_sessions(claude_tree, OLD_ID)[OLD_ID])
    clock.moment = TRASHED_AT + timedelta(seconds=1)

    assert service.plan_empty() == [entry]
