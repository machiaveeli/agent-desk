from datetime import UTC, datetime
from pathlib import Path

import pytest

from agent_desk.domain.models import Project, Session, SessionSummary
from agent_desk.providers.codex import CodexProvider
from agent_desk.providers.codex_summary import FIRST_PROMPT_MAX_LENGTH
from fixtures.codex_tree import (
    CORRUPTED_LINE,
    UNKNOWN_TYPE_LINE,
    CodexTree,
    HistoryMode,
    JsonLine,
    agent_message,
    function_call,
    response_user_message,
    user_message,
    user_message_item,
)

PROVIDER_ID = "codex"
SESSION_ID = "00000000-0000-4000-8000-0000000000c1"
CWD = "/work/app"
CREATED = datetime(2026, 1, 1, 10, 0, 0)


def at_minute(minute: int) -> datetime:
    return datetime(2026, 1, 1, 10, minute, tzinfo=UTC)


def summarize(
    codex_tree: CodexTree, lines: list[JsonLine], history_mode: HistoryMode = "legacy"
) -> SessionSummary:
    codex_tree.add_session(
        SESSION_ID, cwd=CWD, created=CREATED, lines=lines, history_mode=history_mode
    )
    project = Project(PROVIDER_ID, codex_tree.root / "sessions", Path(CWD))
    [summary] = CodexProvider(root=codex_tree.root).list_sessions(project)
    return summary


def test_session_identity_comes_from_the_session_meta(codex_tree: CodexTree) -> None:
    summary = summarize(codex_tree, [user_message("hi")])

    expected_path = codex_tree.root.joinpath(
        "sessions", "2026", "01", "01", f"rollout-2026-01-01T10-00-00-{SESSION_ID}.jsonl"
    )
    # Codex keeps nothing beside a rollout, so there is no sibling dir.
    assert summary.session == Session(PROVIDER_ID, SESSION_ID, expected_path, None, Path(CWD))


def test_title_is_the_last_thread_name_of_the_session_index(codex_tree: CodexTree) -> None:
    codex_tree.add_thread_name(SESSION_ID, "Old name", minute=1)
    codex_tree.add_thread_name("00000000-0000-4000-8000-0000000000ff", "Other session", minute=2)
    codex_tree.add_thread_name(SESSION_ID, "New name", minute=3)

    assert summarize(codex_tree, [user_message("the prompt")]).title == "New name"


@pytest.mark.parametrize(
    ("lines", "expected_title"),
    [
        ([user_message("the prompt")], "the prompt"),
        ([], SESSION_ID),
    ],
    ids=["first-prompt", "session-id"],
)
def test_without_a_thread_name_the_title_falls_back_to_prompt_then_id(
    codex_tree: CodexTree, lines: list[JsonLine], expected_title: str
) -> None:
    assert summarize(codex_tree, lines).title == expected_title


def test_malformed_session_index_lines_are_skipped(codex_tree: CodexTree) -> None:
    codex_tree.add_thread_name(SESSION_ID, "Good name", minute=1)
    with (codex_tree.root / "session_index.jsonl").open("ab") as index:
        index.write(b'{"id": "broken\n{"id": "' + SESSION_ID.encode() + b'", "thread_name": 7}\n')

    assert summarize(codex_tree, [user_message("the prompt")]).title == "Good name"


def test_first_prompt_comes_from_the_user_message_event_not_the_model_input(
    codex_tree: CodexTree,
) -> None:
    # Codex also sends injected context to the model as user messages; only the event is
    # what the user typed.
    lines = [
        response_user_message("<environment_context>cwd</environment_context>"),
        user_message("  fix   the\nbug  "),
        user_message("second prompt"),
    ]

    assert summarize(codex_tree, lines).first_prompt == "fix the bug"


def test_first_prompt_of_a_paginated_rollout_comes_from_the_user_message_item(
    codex_tree: CodexTree,
) -> None:
    lines = [user_message_item("paginated prompt", session_id=SESSION_ID)]

    summary = summarize(codex_tree, lines, history_mode="paginated")

    assert summary.first_prompt == "paginated prompt"


def test_assistant_messages_are_never_the_first_prompt(codex_tree: CodexTree) -> None:
    lines = [agent_message("How can I help?"), user_message("the prompt")]

    assert summarize(codex_tree, lines).first_prompt == "the prompt"


@pytest.mark.parametrize(
    ("prompt", "expected"),
    [
        ("x" * FIRST_PROMPT_MAX_LENGTH, "x" * FIRST_PROMPT_MAX_LENGTH),
        ("x" * (FIRST_PROMPT_MAX_LENGTH + 1), "x" * (FIRST_PROMPT_MAX_LENGTH - 1) + "…"),
    ],
    ids=["at-limit", "past-limit"],
)
def test_first_prompt_is_truncated_only_past_the_limit(
    codex_tree: CodexTree, prompt: str, expected: str
) -> None:
    assert summarize(codex_tree, [user_message(prompt)]).first_prompt == expected


def test_start_and_end_are_the_earliest_and_latest_timestamps(codex_tree: CodexTree) -> None:
    lines = [
        user_message("hi", minute=2),
        function_call("shell", {"command": ["ls"]}, minute=7),
        agent_message("done", minute=5),
    ]

    summary = summarize(codex_tree, lines)

    # The session_meta line is at minute 0.
    assert (summary.started_at, summary.ended_at) == (at_minute(0), at_minute(7))


def test_invalid_lines_are_counted_and_unknown_types_are_not(codex_tree: CodexTree) -> None:
    lines = [CORRUPTED_LINE, UNKNOWN_TYPE_LINE, "[1, 2]", user_message("hi")]

    summary = summarize(codex_tree, lines)

    assert summary.invalid_line_count == 2
    assert summary.first_prompt == "hi"


def test_size_is_the_rollout_file_size(codex_tree: CodexTree) -> None:
    summary = summarize(codex_tree, [user_message("hi")])

    assert summary.size_bytes == summary.session.path.stat().st_size
