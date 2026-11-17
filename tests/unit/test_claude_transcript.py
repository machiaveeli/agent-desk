from pathlib import Path

import pytest

from agent_desk.domain.models import Session, TranscriptEntry
from agent_desk.providers.claude_code import ClaudeCodeProvider
from agent_desk.providers.claude_transcript import TOOL_SUMMARY_MAX_LENGTH
from fixtures.claude_tree import (
    CORRUPTED_LINE,
    UNKNOWN_TYPE_LINE,
    ClaudeTree,
    JsonLine,
    ai_title_line,
    assistant_line,
    custom_title_line,
    text_block,
    thinking_block,
    tool_result_block,
    tool_use_block,
    user_line,
)

SESSION_ID = "00000000-0000-4000-8000-000000000001"
CWD = "/work/app"


def read_transcript(claude_tree: ClaudeTree, lines: list[JsonLine]) -> list[TranscriptEntry]:
    path = claude_tree.add_session(claude_tree.add_project(CWD), SESSION_ID, lines)
    session = Session("claude-code", SESSION_ID, path, None, Path(CWD))
    return list(ClaudeCodeProvider(root=claude_tree.root).read_transcript(session))


def user(text: str) -> TranscriptEntry:
    return TranscriptEntry("user", text)


def assistant(text: str) -> TranscriptEntry:
    return TranscriptEntry("assistant", text)


def tool(name: str, text: str) -> TranscriptEntry:
    return TranscriptEntry("tool", text, tool_name=name)


@pytest.mark.parametrize(
    ("lines", "expected"),
    [
        ([user_line("hello", cwd=CWD)], [user("hello")]),
        ([user_line("  hello\n", cwd=CWD)], [user("hello")]),
        (
            [user_line([text_block("one"), text_block("two")], cwd=CWD)],
            [user("one"), user("two")],
        ),
        ([assistant_line([text_block("hi there")], cwd=CWD)], [assistant("hi there")]),
        (
            [assistant_line([thinking_block("secret plan"), text_block("answer")], cwd=CWD)],
            [assistant("answer")],
        ),
        ([user_line("   ", cwd=CWD), assistant_line([text_block("")], cwd=CWD)], []),
        (
            [assistant_line([{"type": "text", "text": 5}, text_block("ok")], cwd=CWD)],
            [assistant("ok")],
        ),
        (
            [assistant_line([{"type": "image", "name": "pic.png"}, text_block("ok")], cwd=CWD)],
            [assistant("ok")],
        ),
        (
            [assistant_line([text_block("<command-name> is a tag")], cwd=CWD)],
            [assistant("<command-name> is a tag")],
        ),
    ],
    ids=[
        "user-text",
        "text-is-stripped",
        "one-entry-per-text-block",
        "assistant-text",
        "thinking-is-skipped",
        "blank-text-is-skipped",
        "text-block-without-string-is-skipped",
        "other-block-with-a-name-is-skipped",
        "assistant-may-mention-command-tags",
    ],
)
def test_text_messages_become_entries(
    claude_tree: ClaudeTree, lines: list[JsonLine], expected: list[TranscriptEntry]
) -> None:
    assert read_transcript(claude_tree, lines) == expected


@pytest.mark.parametrize(
    ("tool_input", "expected_text"),
    [
        ({"command": "ls -la", "description": "List files"}, "ls -la"),
        ({"todos": [{"content": "x"}], "file_path": "/work/app/a.py"}, "/work/app/a.py"),
        ({"command": "git status\n  && git log"}, "git status && git log"),
        ({"todos": [], "count": 3}, ""),
        ({}, ""),
    ],
    ids=[
        "first-text-argument",
        "non-text-arguments-are-passed-over",
        "whitespace-is-collapsed",
        "no-text-argument",
        "no-arguments",
    ],
)
def test_tool_call_collapses_to_its_name_and_first_text_argument(
    claude_tree: ClaudeTree, tool_input: dict[str, object], expected_text: str
) -> None:
    lines = [assistant_line([tool_use_block("t1", "Bash", tool_input)], cwd=CWD)]

    assert read_transcript(claude_tree, lines) == [tool("Bash", expected_text)]


@pytest.mark.parametrize(
    ("argument", "expected_text"),
    [
        ("x" * TOOL_SUMMARY_MAX_LENGTH, "x" * TOOL_SUMMARY_MAX_LENGTH),
        ("x" * (TOOL_SUMMARY_MAX_LENGTH + 1), "x" * (TOOL_SUMMARY_MAX_LENGTH - 1) + "…"),
    ],
    ids=["at-the-limit-is-kept", "over-the-limit-is-truncated"],
)
def test_tool_call_text_is_truncated_only_past_the_limit(
    claude_tree: ClaudeTree, argument: str, expected_text: str
) -> None:
    lines = [assistant_line([tool_use_block("t1", "Bash", {"command": argument})], cwd=CWD)]

    assert read_transcript(claude_tree, lines) == [tool("Bash", expected_text)]


@pytest.mark.parametrize(
    "block",
    [
        {"type": "tool_use", "id": "t1", "input": {"command": "ls"}},
        {"type": "tool_use", "id": "t1", "name": 7, "input": {"command": "ls"}},
        {"type": "tool_use", "id": "t1", "name": "  ", "input": {"command": "ls"}},
    ],
    ids=["no-name", "name-not-text", "blank-name"],
)
def test_tool_call_without_a_usable_name_is_dropped(
    claude_tree: ClaudeTree, block: dict[str, object]
) -> None:
    lines = [assistant_line([block, text_block("after")], cwd=CWD)]

    assert read_transcript(claude_tree, lines) == [assistant("after")]


def test_tool_call_with_arguments_that_are_not_an_object_keeps_its_name(
    claude_tree: ClaudeTree,
) -> None:
    block: dict[str, object] = {"type": "tool_use", "id": "t1", "name": "Bash", "input": "ls"}

    assert read_transcript(claude_tree, [assistant_line([block], cwd=CWD)]) == [tool("Bash", "")]


def test_tool_results_are_left_out(claude_tree: ClaudeTree) -> None:
    lines = [
        assistant_line([tool_use_block("t1", "Read", {"file_path": "/work/app/a.py"})], cwd=CWD),
        user_line([tool_result_block("t1", "file contents")], cwd=CWD),
        user_line(
            [{"type": "tool_result", "tool_use_id": "t2", "content": [text_block("listed")]}],
            cwd=CWD,
        ),
    ]

    assert read_transcript(claude_tree, lines) == [tool("Read", "/work/app/a.py")]


def test_lines_the_user_did_not_type_are_left_out(claude_tree: ClaudeTree) -> None:
    compact_summary = user_line("This session is being continued...", cwd=CWD)
    assert isinstance(compact_summary, dict)
    compact_summary["isCompactSummary"] = True
    lines = [
        user_line("injected context", cwd=CWD, is_meta=True),
        user_line("<command-name>/clear</command-name>", cwd=CWD),
        user_line("<local-command-stdout>done</local-command-stdout>", cwd=CWD),
        compact_summary,
        user_line("real question", cwd=CWD),
    ]

    assert read_transcript(claude_tree, lines) == [user("real question")]


def test_lines_without_messages_are_skipped(claude_tree: ClaudeTree) -> None:
    lines: list[JsonLine] = [
        CORRUPTED_LINE,
        UNKNOWN_TYPE_LINE,
        custom_title_line("title"),
        ai_title_line("ai"),
        {"type": "user", "message": "not an object"},
        {"type": "assistant", "message": {"content": 42}},
        {"type": "system", "message": {"content": "not part of the conversation"}},
        user_line("hi", cwd=CWD),
    ]

    assert read_transcript(claude_tree, lines) == [user("hi")]


def test_entries_keep_the_conversation_order(claude_tree: ClaudeTree) -> None:
    lines = [
        user_line("list the files", cwd=CWD, minute=1),
        assistant_line([text_block("sure")], cwd=CWD, minute=2),
        assistant_line([tool_use_block("t1", "Bash", {"command": "ls"})], cwd=CWD, minute=3),
        user_line([tool_result_block("t1", "a.py")], cwd=CWD, minute=4),
        assistant_line([text_block("one file")], cwd=CWD, minute=5),
    ]

    assert read_transcript(claude_tree, lines) == [
        user("list the files"),
        assistant("sure"),
        tool("Bash", "ls"),
        assistant("one file"),
    ]
