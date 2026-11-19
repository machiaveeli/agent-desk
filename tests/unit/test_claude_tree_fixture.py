import json
from pathlib import Path

from fixtures.claude_tree import (
    CORRUPTED_LINE,
    ClaudeTree,
    text_block,
    timestamp_at,
    user_line,
)

SESSION_ID = "00000000-0000-4000-8000-000000000001"
CWD = "/work/my-app"


def read_lines(path: Path) -> list[str]:
    return path.read_bytes().decode("utf-8").split("\n")


def test_project_folder_name_encodes_the_cwd_like_claude_code(claude_tree: ClaudeTree) -> None:
    project_dir = claude_tree.add_project(CWD)

    # Only the observed rule: "/" becomes "-". How other characters are encoded was not seen.
    assert project_dir == claude_tree.root / "projects" / "-work-my-app"
    assert project_dir.is_dir()


def test_session_lines_are_written_one_per_line_with_the_session_id(
    claude_tree: ClaudeTree,
) -> None:
    project_dir = claude_tree.add_project(CWD)

    path = claude_tree.add_session(
        project_dir, SESSION_ID, [user_line([text_block("hi")], cwd=CWD), CORRUPTED_LINE]
    )

    first, second, trailing = read_lines(path)
    assert json.loads(first)["sessionId"] == SESSION_ID
    assert second == CORRUPTED_LINE
    assert trailing == ""


def test_sibling_custom_title_lands_next_to_the_transcript(claude_tree: ClaudeTree) -> None:
    project_dir = claude_tree.add_project(CWD)

    path = claude_tree.add_sibling_custom_title(project_dir, SESSION_ID, "Named session")

    assert path == project_dir / SESSION_ID / "custom-title.json"
    assert json.loads(path.read_text(encoding="utf-8")) == {"customTitle": "Named session"}


def test_active_session_file_comes_with_a_key_file_beside_it(claude_tree: ClaudeTree) -> None:
    path = claude_tree.add_active_session_file(pid=4242, session_id=SESSION_ID, cwd=CWD)

    assert json.loads(path.read_text(encoding="utf-8"))["sessionId"] == SESSION_ID
    assert sorted(child.name for child in path.parent.iterdir()) == [
        "4242.fixture.key",
        "4242.json",
    ]


def test_timestamps_are_iso_utc_minutes_after_a_fixed_base() -> None:
    assert timestamp_at(5) == "2026-01-01T10:05:00.000Z"
