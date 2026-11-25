"""Captures a folder tree so tests can prove exactly what changed on disk, or that nothing did."""

from pathlib import Path

# Relative path (always with "/") -> file bytes, or None for a folder.
type TreeSnapshot = dict[str, bytes | None]


def snapshot(root: Path) -> TreeSnapshot:
    """Every file and folder under `root`. A missing root is an empty tree."""
    if not root.exists():
        return {}
    return {
        path.relative_to(root).as_posix(): None if path.is_dir() else path.read_bytes()
        for path in sorted(root.rglob("*"))
    }
