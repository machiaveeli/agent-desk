"""The trash commands, with the trash and the catalog injected through Typer's `obj`."""

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from typer.testing import CliRunner, Result

from agent_desk.cli.main import Dependencies, app
from agent_desk.domain.errors import ConfigError
from agent_desk.domain.models import TrashEntry
from agent_desk.providers.claude_code import ClaudeCodeProvider
from agent_desk.services.catalog import CatalogService
from agent_desk.services.trash import TrashService
from fixtures.claude_tree import ClaudeTree, custom_title_line, user_line
from fixtures.file_tree import snapshot

SESSION_ID = "3f2a9c1e-0000-4000-8000-000000000001"
ENTRY_ID = "20261001T120000Z-3f2a9c1e"
CWD = "/work/app"
TITLE = "Fix the login bug"
TRASHED_AT = datetime(2026, 10, 1, 12, 0, 0, tzinfo=UTC)
RETENTION_DAYS = 30
EXPIRED_AT = TRASHED_AT + timedelta(days=RETENTION_DAYS + 1)
EXIT_FAILURE = 1

runner = CliRunner()


class Clock:
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


def make_trash(trash_root: Path, clock: Clock, catalog: CatalogService) -> TrashService:
    return TrashService(
        root=trash_root, is_active=catalog.is_active, now=clock, retention_days=RETENTION_DAYS
    )


def catalog_for(claude_tree: ClaudeTree) -> CatalogService:
    return CatalogService([ClaudeCodeProvider(root=claude_tree.root)])


def run(
    claude_tree: ClaudeTree,
    trash_root: Path,
    clock: Clock,
    args: list[str],
    user_input: str | None = None,
) -> Result:
    dependencies = Dependencies(
        load_catalog=lambda: catalog_for(claude_tree),
        load_trash=lambda catalog: make_trash(trash_root, clock, catalog),
    )
    return runner.invoke(app, ["trash", *args], obj=dependencies, input=user_input)


def trash_a_session(claude_tree: ClaudeTree, trash_root: Path, clock: Clock) -> TrashEntry:
    project_dir = claude_tree.add_project(CWD)
    claude_tree.add_session(
        project_dir, SESSION_ID, [user_line("hi", cwd=CWD), custom_title_line(TITLE)]
    )
    catalog = catalog_for(claude_tree)
    [overview] = catalog.list_projects().projects
    [summary] = catalog.list_project_sessions(overview.project)
    entry = make_trash(trash_root, clock, catalog).trash(summary)
    assert isinstance(entry, TrashEntry)
    return entry


def test_list_shows_each_entry_with_its_id_status_and_title(
    claude_tree: ClaudeTree, trash_root: Path, clock: Clock
) -> None:
    trash_a_session(claude_tree, trash_root, clock)
    clock.moment = EXPIRED_AT

    result = run(claude_tree, trash_root, clock, ["list"])

    header, row = result.stdout.splitlines()
    assert header.split() == ["ID", "TRASHED", "SIZE", "STATUS", "PROVIDER", "PROJECT", "TITLE"]
    assert row.split()[0] == ENTRY_ID
    assert "expired" in row.split()
    assert row.endswith(TITLE)


def test_list_of_an_empty_trash_says_so(
    claude_tree: ClaudeTree, trash_root: Path, clock: Clock
) -> None:
    result = run(claude_tree, trash_root, clock, ["list"])

    assert (result.exit_code, result.stdout) == (0, "The trash is empty.\n")


def test_list_reports_an_unreadable_entry_on_stderr(
    claude_tree: ClaudeTree, trash_root: Path, clock: Clock
) -> None:
    trash_a_session(claude_tree, trash_root, clock)
    (trash_root / ENTRY_ID / "manifest.json").write_bytes(b"{")

    result = run(claude_tree, trash_root, clock, ["list"])

    assert result.stdout == "The trash is empty.\n"
    assert (
        result.stderr == f"Note: entry {ENTRY_ID} cannot be read: the manifest is not valid JSON.\n"
    )


def test_restore_puts_the_session_back_and_says_where(
    claude_tree: ClaudeTree, trash_root: Path, clock: Clock
) -> None:
    entry = trash_a_session(claude_tree, trash_root, clock)

    result = run(claude_tree, trash_root, clock, ["restore", ENTRY_ID])

    assert result.exit_code == 0
    assert result.stdout == f"Restored '{TITLE}' (claude-code, {Path(CWD)}).\n"
    assert entry.items[0].original_path.exists()


def test_restore_refusal_is_a_clear_error(
    claude_tree: ClaudeTree, trash_root: Path, clock: Clock
) -> None:
    result = run(claude_tree, trash_root, clock, ["restore", "no-such-entry"])

    assert result.exit_code == EXIT_FAILURE
    assert isinstance(result.exception, SystemExit), "a clean exit, not a crash"
    assert result.stderr == "Error: no trash entry with id 'no-such-entry'.\n"


def test_empty_lists_what_it_will_delete_and_stops_on_no(
    claude_tree: ClaudeTree, trash_root: Path, clock: Clock
) -> None:
    trash_a_session(claude_tree, trash_root, clock)
    clock.moment = EXPIRED_AT
    before = snapshot(trash_root)

    result = run(claude_tree, trash_root, clock, ["empty"], user_input="n\n")

    assert result.exit_code == EXIT_FAILURE
    assert ENTRY_ID in result.stdout
    assert "Delete 1 expired entries for good?" in result.stdout
    assert snapshot(trash_root) == before


def test_empty_previews_only_the_expired_entries(
    claude_tree: ClaudeTree, trash_root: Path, clock: Clock
) -> None:
    trash_a_session(claude_tree, trash_root, clock)
    project_dir = claude_tree.add_project(CWD)
    recent_id = "7c7c7c7c-0000-4000-8000-000000000002"
    claude_tree.add_session(project_dir, recent_id, [user_line("later", cwd=CWD)])
    catalog = catalog_for(claude_tree)
    [overview] = catalog.list_projects().projects
    [recent] = catalog.list_project_sessions(overview.project)
    clock.moment = TRASHED_AT + timedelta(days=10)
    make_trash(trash_root, clock, catalog).trash(recent)
    clock.moment = EXPIRED_AT

    result = run(claude_tree, trash_root, clock, ["empty"], user_input="n\n")

    assert ENTRY_ID in result.stdout
    assert recent_id[:8] not in result.stdout


def test_empty_defaults_to_no(claude_tree: ClaudeTree, trash_root: Path, clock: Clock) -> None:
    trash_a_session(claude_tree, trash_root, clock)
    clock.moment = EXPIRED_AT
    before = snapshot(trash_root)

    result = run(claude_tree, trash_root, clock, ["empty"], user_input="\n")

    assert (result.exit_code, snapshot(trash_root)) == (EXIT_FAILURE, before)


def test_empty_deletes_the_expired_entries_after_yes(
    claude_tree: ClaudeTree, trash_root: Path, clock: Clock
) -> None:
    trash_a_session(claude_tree, trash_root, clock)
    clock.moment = EXPIRED_AT

    result = run(claude_tree, trash_root, clock, ["empty"], user_input="y\n")

    assert result.exit_code == 0
    assert result.stdout.endswith("Deleted 1 entries.\n")
    assert snapshot(trash_root) == {}


def test_empty_with_nothing_expired_deletes_nothing_and_asks_nothing(
    claude_tree: ClaudeTree, trash_root: Path, clock: Clock
) -> None:
    trash_a_session(claude_tree, trash_root, clock)
    before = snapshot(trash_root)

    result = run(claude_tree, trash_root, clock, ["empty"])

    assert (result.exit_code, result.stdout) == (0, "No expired entries to delete.\n")
    assert snapshot(trash_root) == before


def test_a_config_error_stops_the_trash_commands(
    claude_tree: ClaudeTree, trash_root: Path, clock: Clock
) -> None:
    error = ConfigError("trash.retention_days", "out_of_range", "'trash.retention_days' bad")
    dependencies = Dependencies(
        load_catalog=lambda: catalog_for(claude_tree), load_trash=lambda catalog: error
    )

    result = runner.invoke(app, ["trash", "list"], obj=dependencies)

    assert result.exit_code == EXIT_FAILURE
    assert result.stderr == "Error: config: 'trash.retention_days' bad\n"
