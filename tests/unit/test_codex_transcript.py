from datetime import datetime

import pytest

from agent_desk.domain.models import Session, TranscriptEntry
from agent_desk.providers.codex import CodexProvider
from agent_desk.providers.codex_transcript import TOOL_SUMMARY_MAX_LENGTH
from fixtures.codex_tree import (
    CORRUPTED_LINE,
    UNKNOWN_TYPE_LINE,
    CodexTree,
    HistoryMode,
    JsonLine,
    agent_message,
    agent_message_item,
    custom_tool_call,
    envelope,
    function_call,
    local_shell_call,
    response_user_message,
    user_message,
    user_message_item,
)

PROVIDER_ID = "codex"
SESSION_ID = "00000000-0000-4000-8000-0000000000c1"
CWD = "/work/app"
CREATED = datetime(2026, 1, 1, 10, 0, 0)


def read_transcript(
    codex_tree: CodexTree, lines: list[JsonLine], history_mode: HistoryMode = "legacy"
) -> list[TranscriptEntry]:
    path = codex_tree.add_session(
        SESSION_ID, cwd=CWD, created=CREATED, lines=lines, history_mode=history_mode
    )
    session = Session(PROVIDER_ID, SESSION_ID, path, None, None)
    return list(CodexProvider(root=codex_tree.root).read_transcript(session))


def test_legacy_message_events_become_entries(codex_tree: CodexTree) -> None:
    lines = [user_message(" fix it "), agent_message("Done.")]

    assert read_transcript(codex_tree, lines) == [
        TranscriptEntry("user", "fix it"),
        TranscriptEntry("assistant", "Done."),
    ]


def test_paginated_message_items_become_entries(codex_tree: CodexTree) -> None:
    lines = [
        user_message_item("fix it", session_id=SESSION_ID),
        agent_message_item("Done.", session_id=SESSION_ID),
    ]

    assert read_transcript(codex_tree, lines, history_mode="paginated") == [
        TranscriptEntry("user", "fix it"),
        TranscriptEntry("assistant", "Done."),
    ]


def test_model_input_messages_are_left_out(codex_tree: CodexTree) -> None:
    # The same text reaches the model as a response_item; showing both would duplicate it,
    # and the response_item also carries injected context the user never typed.
    lines = [response_user_message("<environment_context>cwd</environment_context>")]

    assert read_transcript(codex_tree, lines) == []


@pytest.mark.parametrize(
    ("line", "expected"),
    [
        (
            function_call("shell", {"command": "ls -la", "timeout_ms": 1000}),
            TranscriptEntry("tool", "ls -la", tool_name="shell"),
        ),
        (
            function_call("update_plan", {"plan": [{"step": "read"}]}),
            TranscriptEntry("tool", "", tool_name="update_plan"),
        ),
        (
            custom_tool_call("apply_patch", "*** Begin Patch\n*** Update File: a.py"),
            TranscriptEntry(
                "tool", "*** Begin Patch *** Update File: a.py", tool_name="apply_patch"
            ),
        ),
        (
            local_shell_call(["bash", "-lc", "ls"]),
            TranscriptEntry("tool", "bash -lc ls", tool_name="local_shell_call"),
        ),
    ],
    ids=["function-call", "no-text-argument", "custom-tool", "local-shell"],
)
def test_tool_call_collapses_to_its_name_and_first_text_argument(
    codex_tree: CodexTree, line: JsonLine, expected: TranscriptEntry
) -> None:
    assert read_transcript(codex_tree, [line]) == [expected]


def test_tool_call_text_is_truncated_only_past_the_limit(codex_tree: CodexTree) -> None:
    lines = [
        function_call("shell", {"command": "x" * TOOL_SUMMARY_MAX_LENGTH}),
        function_call("shell", {"command": "x" * (TOOL_SUMMARY_MAX_LENGTH + 1)}),
    ]

    assert [entry.text for entry in read_transcript(codex_tree, lines)] == [
        "x" * TOOL_SUMMARY_MAX_LENGTH,
        "x" * (TOOL_SUMMARY_MAX_LENGTH - 1) + "…",
    ]


def test_function_call_with_arguments_that_are_not_json_keeps_its_name(
    codex_tree: CodexTree,
) -> None:
    payload = {"type": "function_call", "name": "shell", "arguments": "{not json", "call_id": "c"}

    entries = read_transcript(codex_tree, [envelope("response_item", payload, 0)])

    assert entries == [TranscriptEntry("tool", "", tool_name="shell")]


def test_tool_call_without_a_usable_name_is_dropped(codex_tree: CodexTree) -> None:
    payload = {"type": "function_call", "name": " ", "arguments": "{}", "call_id": "c"}

    assert read_transcript(codex_tree, [envelope("response_item", payload, 0)]) == []


def test_broken_unknown_and_empty_lines_are_skipped(codex_tree: CodexTree) -> None:
    lines = [CORRUPTED_LINE, UNKNOWN_TYPE_LINE, user_message("   "), agent_message("ok")]

    assert read_transcript(codex_tree, lines) == [TranscriptEntry("assistant", "ok")]


def test_entries_keep_the_conversation_order(codex_tree: CodexTree) -> None:
    lines = [
        user_message("list files"),
        function_call("shell", {"command": "ls"}),
        agent_message("Here they are."),
    ]

    assert [entry.role for entry in read_transcript(codex_tree, lines)] == [
        "user",
        "tool",
        "assistant",
    ]
