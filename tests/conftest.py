from pathlib import Path

import pytest

from fixtures.claude_tree import ClaudeTree


@pytest.fixture
def claude_tree(tmp_path: Path) -> ClaudeTree:
    """An empty synthetic ~/.claude; the root folder only exists once something is added."""
    return ClaudeTree(tmp_path / "home" / ".claude")
