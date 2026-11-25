"""Moves a file or folder, also across volumes, without ever losing the source.

`Path.rename` is instant and atomic but only works within one filesystem; across volumes it
fails with errno EXDEV (on Windows too: CPython maps ERROR_NOT_SAME_DEVICE, 17, to EXDEV).
Then the item is copied, the copy is checked against the source, and only then is the source
removed. If anything fails before that, the partial copy is removed and the source is intact."""

import errno
import hashlib
import shutil
from collections.abc import Callable
from pathlib import Path

type Rename = Callable[[Path, Path], object]
# Same signature as shutil.copy2, which copytree also accepts as copy_function.
type FileCopier = Callable[[str, str], object]
# Relative path (with "/") -> sha256 of the content, or None for a folder.
type TreeFingerprint = dict[str, str | None]


def move_path(
    source: Path,
    target: Path,
    *,
    rename: Rename = Path.rename,
    copy_file: FileCopier = shutil.copy2,
) -> None:
    try:
        rename(source, target)
    except OSError as error:
        if error.errno != errno.EXDEV:
            raise
        copy_verify_and_remove(source, target, copy_file)


def copy_verify_and_remove(source: Path, target: Path, copy_file: FileCopier) -> None:
    # Checked first because a failed copy removes the target, which must never be someone
    # else's file.
    if target.exists() or target.is_symlink():
        raise FileExistsError(errno.EEXIST, "the target already exists", str(target))
    try:
        copy_item(source, target, copy_file)
        if fingerprint(source) != fingerprint(target):
            raise OSError(f"the copy of {source} does not match the original")
    except BaseException:
        remove_item(target)
        raise
    remove_item(source)


def copy_item(source: Path, target: Path, copy_file: FileCopier) -> None:
    if source.is_dir():
        # symlinks=True copies a link as a link, so nothing outside the folder is pulled in.
        shutil.copytree(source, target, symlinks=True, copy_function=copy_file)
    else:
        copy_file(str(source), str(target))


def fingerprint(root: Path) -> TreeFingerprint:
    if not root.is_dir():
        return {"": file_fingerprint(root)}
    return {
        path.relative_to(root).as_posix(): None if path.is_dir() else file_fingerprint(path)
        for path in root.rglob("*")
    }


def file_fingerprint(path: Path) -> str:
    """The sha256 alone: an equal hash already implies an equal size."""
    with path.open("rb") as file:
        return hashlib.file_digest(file, "sha256").hexdigest()


def remove_item(path: Path) -> None:
    if path.is_dir():
        shutil.rmtree(path)
    else:
        path.unlink(missing_ok=True)
