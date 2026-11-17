from datetime import UTC, datetime
from pathlib import Path

import pytest

from agent_desk.domain.models import SessionSummary
from agent_desk.providers.claude_summary import FIRST_PROMPT_MAX_LENGTH, summarize_session
from fixtures.claude_tree import (
    CORRUPTED_LINE,
    UNKNOWN_TYPE_LINE,
    ClaudeTree,
    JsonLine,
    ai_title_line,
    assistant_line,
    custom_title_line,
    text_block,
    timestamp_at,
    tool_result_block,
    user_line,
)

PROVIDER_ID = "claude-code"
SESSION_ID = "00000000-0000-4000-8000-000000000001"
CWD = "/work/app"


@pytest.fixture
def project_dir(claude_tree: ClaudeTree) -> Path:
    return claude_tree.add_project(CWD)


def at_minute(minute: int) -> datetime:
    return datetime(2026, 1, 1, 10, minute, tzinfo=UTC)


def summarize(claude_tree: ClaudeTree, project_dir: Path, lines: list[JsonLine]) -> SessionSummary:
    path = claude_tree.add_session(project_dir, SESSION_ID, lines)
    return summarize_session(path, PROVIDER_ID)


@pytest.mark.parametrize(
    ("lines", "expected_title"),
    [
        (
            [ai_title_line("ai"), custom_title_line("first"), custom_title_line("second")],
            "second",
        ),
        ([user_line("hello", cwd=CWD), ai_title_line("a1"), ai_title_line("a2")], "a2"),
        ([custom_title_line(""), ai_title_line("ai")], "ai"),
        ([custom_title_line("   "), ai_title_line("ai")], "ai"),
        ([custom_title_line("  padded  ")], "padded"),
        ([user_line("hello", cwd=CWD)], "hello"),
        ([custom_title_line("only")], "only"),
        ([], SESSION_ID),
    ],
    ids=[
        "last-custom-title-wins",
        "last-ai-title-beats-first-prompt",
        "empty-custom-title-is-ignored",
        "blank-custom-title-is-ignored",
        "title-is-stripped",
        "first-prompt-when-no-title",
        "custom-title-alone",
        "session-id-when-nothing-else",
    ],
)
def test_title_follows_the_priority_order(
    claude_tree: ClaudeTree, project_dir: Path, lines: list[JsonLine], expected_title: str
) -> None:
    summary = summarize(claude_tree, project_dir, lines)

    assert summary.title == expected_title


def test_sibling_title_file_beats_the_ai_title(claude_tree: ClaudeTree, project_dir: Path) -> None:
    claude_tree.add_sibling_custom_title(project_dir, SESSION_ID, "from file")

    summary = summarize(claude_tree, project_dir, [ai_title_line("ai")])

    assert summary.title == "from file"


def test_custom_title_line_beats_the_sibling_title_file(
    claude_tree: ClaudeTree, project_dir: Path
) -> None:
    claude_tree.add_sibling_custom_title(project_dir, SESSION_ID, "from file")

    summary = summarize(claude_tree, project_dir, [custom_title_line("from line")])

    assert summary.title == "from line"


def test_malformed_sibling_title_file_is_skipped(
    claude_tree: ClaudeTree, project_dir: Path
) -> None:
    claude_tree.add_sibling_file(project_dir, SESSION_ID, "custom-title.json", "{not json")

    summary = summarize(claude_tree, project_dir, [ai_title_line("ai")])

    assert summary.title == "ai"


@pytest.mark.parametrize(
    ("lines", "expected_prompt"),
    [
        ([user_line("plain text", cwd=CWD)], "plain text"),
        ([user_line([text_block("one"), text_block("two")], cwd=CWD)], "one two"),
        ([user_line("meta", cwd=CWD, is_meta=True), user_line("real", cwd=CWD)], "real"),
        (
            [user_line([tool_result_block("t1", "output")], cwd=CWD), user_line("real", cwd=CWD)],
            "real",
        ),
        (
            [
                user_line("<command-name>/clear</command-name>", cwd=CWD),
                user_line("<local-command-stdout></local-command-stdout>", cwd=CWD),
                user_line("real", cwd=CWD),
            ],
            "real",
        ),
        ([user_line("  hello\n\n  world ", cwd=CWD)], "hello world"),
        ([user_line([{"type": "text", "text": 5}, text_block("ok")], cwd=CWD)], "ok"),
        ([user_line([{"type": "image", "text": "alt"}, text_block("ok")], cwd=CWD)], "ok"),
        ([user_line("first", cwd=CWD), user_line("second", cwd=CWD)], "first"),
        ([assistant_line([text_block("hi")], cwd=CWD)], None),
        ([user_line("   ", cwd=CWD)], None),
    ],
    ids=[
        "string-content",
        "text-blocks-are-joined",
        "meta-line-is-skipped",
        "tool-result-only-is-skipped",
        "local-command-lines-are-skipped",
        "whitespace-is-collapsed",
        "text-block-without-string-is-skipped",
        "non-text-block-is-skipped",
        "only-the-first-prompt",
        "no-user-line",
        "blank-prompt",
    ],
)
def test_first_prompt_is_the_first_real_user_message(
    claude_tree: ClaudeTree,
    project_dir: Path,
    lines: list[JsonLine],
    expected_prompt: str | None,
) -> None:
    summary = summarize(claude_tree, project_dir, lines)

    assert summary.first_prompt == expected_prompt


@pytest.mark.parametrize(
    ("prompt", "expected_prompt"),
    [
        ("x" * FIRST_PROMPT_MAX_LENGTH, "x" * FIRST_PROMPT_MAX_LENGTH),
        ("x" * (FIRST_PROMPT_MAX_LENGTH + 1), "x" * (FIRST_PROMPT_MAX_LENGTH - 1) + "…"),
    ],
    ids=["at-the-limit-is-kept", "over-the-limit-is-truncated"],
)
def test_first_prompt_is_truncated_only_past_the_limit(
    claude_tree: ClaudeTree, project_dir: Path, prompt: str, expected_prompt: str
) -> None:
    summary = summarize(claude_tree, project_dir, [user_line(prompt, cwd=CWD)])

    assert summary.first_prompt == expected_prompt


def test_start_and_end_are_the_earliest_and_latest_timestamps(
    claude_tree: ClaudeTree, project_dir: Path
) -> None:
    lines: list[JsonLine] = [
        user_line("hi", cwd=CWD, minute=20),
        {"type": "system", "timestamp": timestamp_at(5)},
        custom_title_line("no timestamp"),
        {"type": "system", "timestamp": "not a date"},
        {"type": "system", "timestamp": "2026-01-01T10:59:00"},
        assistant_line([text_block("hi")], cwd=CWD, minute=40),
    ]

    summary = summarize(claude_tree, project_dir, lines)

    assert (summary.started_at, summary.ended_at) == (at_minute(5), at_minute(40))


def test_session_without_timestamps_has_no_dates(
    claude_tree: ClaudeTree, project_dir: Path
) -> None:
    summary = summarize(claude_tree, project_dir, [custom_title_line("t")])

    assert (summary.started_at, summary.ended_at) == (None, None)


def test_invalid_lines_are_counted_and_unknown_types_are_not(
    claude_tree: ClaudeTree, project_dir: Path
) -> None:
    lines = [CORRUPTED_LINE, UNKNOWN_TYPE_LINE, user_line("hi", cwd=CWD), CORRUPTED_LINE]

    summary = summarize(claude_tree, project_dir, lines)

    assert summary.invalid_line_count == 2
    assert summary.first_prompt == "hi"


def test_size_adds_the_transcript_and_every_file_in_the_sibling_dir(
    claude_tree: ClaudeTree, project_dir: Path
) -> None:
    claude_tree.add_sibling_file(project_dir, SESSION_ID, "tool-results/a.txt", "12345")
    claude_tree.add_sibling_file(project_dir, SESSION_ID, "subagents/deep/b.txt", "123")

    summary = summarize(claude_tree, project_dir, [user_line("hi", cwd=CWD)])

    assert summary.size_bytes == summary.session.path.stat().st_size + 8


def test_session_identity_comes_from_the_file_and_its_first_cwd(
    claude_tree: ClaudeTree, project_dir: Path
) -> None:
    claude_tree.add_sibling_custom_title(project_dir, SESSION_ID, "t")
    lines = [custom_title_line("t"), user_line("hi", cwd=CWD), user_line("hi", cwd="/other")]

    session = summarize(claude_tree, project_dir, lines).session

    assert (session.provider_id, session.session_id, session.sibling_dir, session.cwd) == (
        PROVIDER_ID,
        SESSION_ID,
        project_dir / SESSION_ID,
        Path(CWD),
    )


def test_session_without_sibling_dir_has_none(claude_tree: ClaudeTree, project_dir: Path) -> None:
    session = summarize(claude_tree, project_dir, [user_line("hi", cwd=CWD)]).session

    assert session.sibling_dir is None
