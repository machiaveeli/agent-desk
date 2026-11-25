"""Moving across volumes: os.rename fails with errno EXDEV when source and target are on
different filesystems (on Windows, CPython maps ERROR_NOT_SAME_DEVICE 17 to EXDEV). The tests
simulate it by injecting a rename that raises that error, since CI has a single volume."""

import errno
import shutil
from functools import partial
from pathlib import Path

import pytest

from agent_desk.services.file_move import move_path
from fixtures.file_tree import snapshot

SESSION_BYTES = b'{"type": "user"}\n'


def cross_device_rename(source: Path, target: Path) -> None:
    raise OSError(errno.EXDEV, "Invalid cross-device link")


def denied_rename(source: Path, target: Path) -> None:
    raise PermissionError(errno.EACCES, "Permission denied")


class FailingCopy:
    """Copies like shutil.copy2 until it reaches a file named `fail_on`, then raises midway."""

    def __init__(self, fail_on: str) -> None:
        self.fail_on = fail_on
        self.copied: list[str] = []

    def __call__(self, source: str, target: str) -> object:
        if Path(source).name == self.fail_on:
            raise OSError(errno.ENOSPC, "No space left on device")
        self.copied.append(Path(source).name)
        return shutil.copy2(source, target)


def corrupting_copy(source: str, target: str) -> object:
    """A copy that silently writes the wrong bytes, like a flaky disk."""
    Path(target).write_bytes(b"x" * Path(source).stat().st_size)
    return target


def make_sibling_dir(parent: Path) -> Path:
    folder = parent / "session"
    (folder / "subagents").mkdir(parents=True)
    (folder / "subagents" / "agent-1.jsonl").write_bytes(b"{}\n")
    (folder / "subagents" / "agent-2.jsonl").write_bytes(b'{"a": 1}\n')
    (folder / "custom-title.json").write_bytes(b'{"customTitle": "t"}')
    (folder / "empty").mkdir()
    return folder


@pytest.fixture
def volumes(tmp_path: Path) -> tuple[Path, Path]:
    source_volume = tmp_path / "source"
    target_volume = tmp_path / "target"
    source_volume.mkdir()
    target_volume.mkdir()
    return source_volume, target_volume


def test_on_the_same_volume_the_file_is_renamed(volumes: tuple[Path, Path]) -> None:
    source_volume, target_volume = volumes
    source = source_volume / "session.jsonl"
    source.write_bytes(SESSION_BYTES)

    move_path(source, target_volume / "session.jsonl")

    assert (source.exists(), (target_volume / "session.jsonl").read_bytes()) == (
        False,
        SESSION_BYTES,
    )


def test_across_volumes_a_file_is_copied_and_then_removed(volumes: tuple[Path, Path]) -> None:
    source_volume, target_volume = volumes
    source = source_volume / "session.jsonl"
    source.write_bytes(SESSION_BYTES)

    move_path(source, target_volume / "session.jsonl", rename=cross_device_rename)

    assert (source.exists(), (target_volume / "session.jsonl").read_bytes()) == (
        False,
        SESSION_BYTES,
    )


def test_across_volumes_a_folder_is_copied_whole_and_then_removed(
    volumes: tuple[Path, Path],
) -> None:
    source_volume, target_volume = volumes
    folder = make_sibling_dir(source_volume)
    before = snapshot(folder)

    move_path(folder, target_volume / "session", rename=cross_device_rename)

    assert (folder.exists(), snapshot(target_volume / "session")) == (False, before)


def test_across_volumes_a_link_inside_the_folder_stays_a_link(
    volumes: tuple[Path, Path],
) -> None:
    source_volume, target_volume = volumes
    folder = make_sibling_dir(source_volume)
    outside = source_volume / "outside.txt"
    outside.write_bytes(b"not part of the session\n")
    try:
        (folder / "link.txt").symlink_to(outside)
    except OSError:
        pytest.skip("this system does not allow creating symlinks")

    move_path(folder, target_volume / "session", rename=cross_device_rename)

    moved_link = target_volume / "session" / "link.txt"
    assert (moved_link.is_symlink(), moved_link.readlink()) == (True, outside)


def test_a_copy_that_fails_midway_leaves_the_source_intact_and_no_partial_target(
    volumes: tuple[Path, Path],
) -> None:
    source_volume, target_volume = volumes
    folder = make_sibling_dir(source_volume)
    before = snapshot(source_volume)
    copy = FailingCopy(fail_on="agent-2.jsonl")

    with pytest.raises(OSError, match="No space left"):
        move_path(folder, target_volume / "session", rename=cross_device_rename, copy_file=copy)

    assert copy.copied != []
    assert (snapshot(source_volume), snapshot(target_volume)) == (before, {})


def test_a_copy_whose_content_differs_is_discarded_and_the_source_stays(
    volumes: tuple[Path, Path],
) -> None:
    source_volume, target_volume = volumes
    source = source_volume / "session.jsonl"
    source.write_bytes(SESSION_BYTES)

    with pytest.raises(OSError, match="does not match"):
        move_path(
            source,
            target_volume / "session.jsonl",
            rename=cross_device_rename,
            copy_file=corrupting_copy,
        )

    assert (source.read_bytes(), snapshot(target_volume)) == (SESSION_BYTES, {})


def test_a_folder_copy_with_one_differing_file_is_discarded_and_the_source_stays(
    volumes: tuple[Path, Path],
) -> None:
    source_volume, target_volume = volumes
    folder = make_sibling_dir(source_volume)
    before = snapshot(source_volume)

    with pytest.raises(OSError, match="does not match"):
        move_path(
            folder,
            target_volume / "session",
            rename=cross_device_rename,
            copy_file=partial(copy_corrupting_only, "custom-title.json"),
        )

    assert (snapshot(source_volume), snapshot(target_volume)) == (before, {})


def test_an_existing_target_is_never_overwritten_nor_removed(volumes: tuple[Path, Path]) -> None:
    source_volume, target_volume = volumes
    source = source_volume / "session.jsonl"
    source.write_bytes(SESSION_BYTES)
    (target_volume / "session.jsonl").write_bytes(b"someone else's file\n")
    before = snapshot(source_volume), snapshot(target_volume)

    with pytest.raises(FileExistsError):
        move_path(source, target_volume / "session.jsonl", rename=cross_device_rename)

    assert (snapshot(source_volume), snapshot(target_volume)) == before


def test_any_other_rename_error_is_raised_without_copying(volumes: tuple[Path, Path]) -> None:
    source_volume, target_volume = volumes
    source = source_volume / "session.jsonl"
    source.write_bytes(SESSION_BYTES)

    with pytest.raises(PermissionError):
        move_path(source, target_volume / "session.jsonl", rename=denied_rename)

    assert (source.read_bytes(), snapshot(target_volume)) == (SESSION_BYTES, {})


def copy_corrupting_only(name: str, source: str, target: str) -> object:
    if Path(source).name == name:
        return corrupting_copy(source, target)
    return shutil.copy2(source, target)
