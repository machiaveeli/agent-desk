import time

import pytest

from agent_desk.providers.claude_summary import summarize_session
from fixtures.claude_tree import ClaudeTree

SESSION_ID = "00000000-0000-4000-8000-000000000001"
CWD = "/work/app"
FIVE_MEGABYTES = 5 * 1024 * 1024
TIME_LIMIT_SECONDS = 1.0


@pytest.mark.slow
def test_summary_of_a_five_megabyte_session_takes_under_a_second(
    claude_tree: ClaudeTree,
) -> None:
    project_dir = claude_tree.add_project(CWD)
    path = claude_tree.add_large_session(
        project_dir, SESSION_ID, cwd=CWD, min_size_bytes=FIVE_MEGABYTES
    )
    assert path.stat().st_size >= FIVE_MEGABYTES

    started = time.perf_counter()
    summarize_session(path, "claude-code")
    elapsed = time.perf_counter() - started

    assert elapsed < TIME_LIMIT_SECONDS
