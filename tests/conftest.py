from pathlib import Path

import pytest

from fixtures.claude_tree import ClaudeTree
from fixtures.codex_tree import CodexTree


@pytest.fixture
def claude_tree(tmp_path: Path) -> ClaudeTree:
    """An empty synthetic ~/.claude; the root folder only exists once something is added."""
    return ClaudeTree(tmp_path / "home" / ".claude")


@pytest.fixture
def codex_tree(tmp_path: Path) -> CodexTree:
    """An empty synthetic ~/.codex; the root folder only exists once something is added."""
    return CodexTree(tmp_path / "home" / ".codex")
